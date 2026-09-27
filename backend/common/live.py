"""Live updates over WebSockets (PLAN §3.1, task 4.6, ADR-044).

The browser can't send the access token on a WebSocket handshake, so it first asks for a one-time
ticket (``POST /api/v1/auth/ws-ticket``, 30 s) and connects to ``/ws/v1/?ticket=…``. The ticket
carries everything the connection may receive; the socket never touches the database.

Groups (T5, per tenant): staff who may view orders join ``orders.<tenant>``; a shop's logins join
``shop.<retailer>``. Messages only say what changed (event, order, status): clients refetch
through the API, which applies the permissions again. Sales staff limited to their own shops get
only their shops' events.
"""

import secrets
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qs
from uuid import UUID

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.cache import cache

TICKET_SECONDS = 30
_PREFIX = "ws-ticket:"
CLOSE_UNAUTHORISED = 4401


@dataclass(frozen=True)
class Grant:
    user_id: str
    tenant_id: str
    retailer_id: str | None = None  # a shop login
    orders: bool = False  # staff with orders.view
    own_shops_only: bool = False  # sales staff limited to their shops (orders.sales_visibility)


def orders_group(tenant_id: UUID | str) -> str:
    return f"orders.{tenant_id}"


def shop_group(retailer_id: UUID | str) -> str:
    return f"shop.{retailer_id}"


def issue_ticket(grant: Grant) -> str:
    ticket = secrets.token_urlsafe(32)
    cache.set(f"{_PREFIX}{ticket}", asdict(grant), timeout=TICKET_SECONDS)
    return ticket


def redeem_ticket(ticket: str) -> Grant | None:
    """One use only: the first connection with a ticket gets it; a second finds nothing."""
    if not ticket or len(ticket) > 100:
        return None
    key = f"{_PREFIX}{ticket}"
    found = cache.get(key)
    if not isinstance(found, dict) or not cache.delete(key):
        return None
    return Grant(**found)


def groups_for(grant: Grant) -> list[str]:
    if grant.retailer_id:
        return [shop_group(grant.retailer_id)]
    return [orders_group(grant.tenant_id)] if grant.orders else []


class LiveConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]
    """``/ws/v1/?ticket=…``: server → client only."""

    grant: Grant | None = None
    joined: list[str]

    async def connect(self) -> None:
        self.joined = []
        query = parse_qs(self.scope.get("query_string", b"").decode())
        grant = await sync_to_async(redeem_ticket)((query.get("ticket") or [""])[0])
        if grant is None:
            await self.close(code=CLOSE_UNAUTHORISED)
            return
        self.grant = grant
        for group in groups_for(grant):
            await self.channel_layer.group_add(group, self.channel_name)
            self.joined.append(group)
        await self.accept()
        await self.send_json({"type": "ready"})

    async def disconnect(self, code: int) -> None:
        for group in getattr(self, "joined", []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def live_event(self, message: dict[str, Any]) -> None:
        data = dict(message["data"])
        salesperson = data.pop("salesperson_id", None)
        if (
            self.grant is not None
            and self.grant.own_shops_only
            and salesperson != self.grant.user_id
        ):
            return
        await self.send_json(data)
