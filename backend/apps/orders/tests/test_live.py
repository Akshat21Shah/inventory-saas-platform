"""Live updates (PLAN task 4.6): one-time tickets, the socket, and who hears what. Staff hear
their tenant's order events (sales staff limited to their shops hear only those); a shop hears
its own orders, never another shop's or the internal backorder proposals."""

import json
from decimal import Decimal as D
from typing import Any

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from asgiref.testing import ApplicationCommunicator
from django.core.cache import cache

from apps.accounts.tests.factories import make_staff_in, make_super_admin
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_stock, client_for, make_shop, place, settings, shop_client
from apps.retailers.models import Retailer
from common.live import Grant, LiveConsumer, issue_ticket, redeem_ticket
from common.models import OutboxEvent
from common.outbox import dispatch_event
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # Consumers close stale DB connections on each message (right in production); here that
    # would end the test's transaction. The live consumer itself never uses the database.
    async def keep() -> None:
        return None

    monkeypatch.setattr("channels.consumer.aclose_old_connections", keep)
    cache.clear()
    yield
    cache.clear()


def _ticket(client) -> str:
    response = client.post("/api/v1/auth/ws-ticket/")
    assert response.status_code == 200, response.json()
    assert response.json()["expires_in"] == 30
    return str(response.json()["ticket"])


def _event_ids(tenant, event_type: str) -> list[str]:
    with tenant_context(tenant.pk):
        return [
            str(pk)
            for pk in OutboxEvent.objects.filter(event_type=event_type)
            .order_by("created_at")
            .values_list("pk", flat=True)
        ]


class Socket(ApplicationCommunicator):
    """A WebSocket client for the consumer (channels.testing needs daphne, which we don't use)."""

    def __init__(self, ticket: str) -> None:
        scope = {
            "type": "websocket",
            "path": "/ws/v1/",
            "query_string": f"ticket={ticket}".encode(),
            "headers": [],
            "subprotocols": [],
        }
        super().__init__(LiveConsumer.as_asgi(), scope)

    async def connect(self) -> tuple[bool, int | None]:
        await self.send_input({"type": "websocket.connect"})
        reply = await self.receive_output(1)
        if reply["type"] == "websocket.close":
            return False, reply.get("code")
        return True, None

    async def receive_json_from(self) -> Any:
        reply = await self.receive_output(1)
        assert reply["type"] == "websocket.send", reply
        return json.loads(reply["text"])

    async def disconnect(self) -> None:
        await self.send_input({"type": "websocket.disconnect", "code": 1000})
        await self.wait(1)


def listen(tickets: dict[str, str], event_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Open a socket per ticket, dispatch the outbox events (eager: the push runs inline), and
    return what each socket received."""

    async def run() -> dict[str, list[dict[str, Any]]]:
        sockets = {}
        for name, ticket in tickets.items():
            socket = Socket(ticket)
            connected, _ = await socket.connect()
            assert connected, name
            assert await socket.receive_json_from() == {"type": "ready"}
            sockets[name] = socket
        for event_id in event_ids:
            await sync_to_async(dispatch_event)(event_id)  # keeps the test's connection
        heard: dict[str, list[dict[str, Any]]] = {}
        for name, socket in sockets.items():
            heard[name] = []
            while not await socket.receive_nothing(timeout=0.05):
                heard[name].append(await socket.receive_json_from())
            await socket.disconnect()
        return heard

    return async_to_sync(run)()


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a, shop_name="Ganesh Traders")
    product = make_product(tenant_a, "A", base_price=D("100"))
    add_stock(tenant_a, product, "10")
    return {"t": tenant_a, "owner": owner, "shop": shop, "product": product}


@covers("auth-ws-ticket")
def test_tickets(world, tenant_b):
    assert client_for(world["t"], world["owner"]).post("/api/v1/auth/ws-ticket/").status_code == 200
    assert shop_client(world["t"], world["shop"]).post("/api/v1/auth/ws-ticket/").status_code == 200
    from rest_framework.test import APIClient

    assert APIClient().post("/api/v1/auth/ws-ticket/").status_code == 401
    admin = APIClient()
    from apps.accounts.tokens import issue_tokens

    token = issue_tokens(make_super_admin(), None).access
    admin.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert admin.post("/api/v1/auth/ws-ticket/").status_code in (401, 403)
    ticket = issue_ticket(Grant("u", str(world["t"].pk), orders=True))
    assert redeem_ticket(ticket) is not None
    assert redeem_ticket(ticket) is None  # once only
    assert redeem_ticket("made-up") is None


def test_a_socket_without_a_valid_ticket_is_refused():
    async def run() -> tuple[bool, int | None]:
        socket = Socket("nope")
        connected, close_code = await socket.connect()
        return connected, close_code

    assert async_to_sync(run)() == (False, 4401)


def test_who_hears_what(world, tenant_b):
    neighbour = make_shop(world["t"], "9876500098")
    tickets = {
        "staff": _ticket(client_for(world["t"], world["owner"])),
        "shop": _ticket(shop_client(world["t"], world["shop"])),
        "neighbour": _ticket(shop_client(world["t"], neighbour)),
        "other_tenant": _ticket(client_for(tenant_b, make_staff_in(tenant_b, "OWNER"))),
    }
    place(world["t"], world["shop"], (world["product"], "2"))
    heard = listen(tickets, _event_ids(world["t"], "order.placed"))
    [staff_event] = heard["staff"]
    assert staff_event["event"] == "order.placed"
    assert (staff_event["retailer_name"], staff_event["status"]) == ("Ganesh Traders", "PLACED")
    assert "salesperson_id" not in staff_event
    [shop_event] = heard["shop"]
    assert set(shop_event) == {"type", "event", "order", "number", "status"}
    assert heard["neighbour"] == [] and heard["other_tenant"] == []


def test_shops_do_not_hear_internal_backorder_events(world):
    from apps.inventory import receipts
    from apps.orders import transitions

    other = make_product(world["t"], "B", base_price=D("50"))
    order = place(world["t"], world["shop"], (other, "2"))
    with tenant_context(world["t"].pk):
        transitions.accept_order(order.pk, by=world["owner"])
        receipts.create_and_post(
            receipts.ReceiptInput(lines=[receipts.LineInput(other.pk, D("2"))]), by=world["owner"]
        )
    tickets = {
        "staff": _ticket(client_for(world["t"], world["owner"])),
        "shop": _ticket(shop_client(world["t"], world["shop"])),
    }
    heard = listen(tickets, _event_ids(world["t"], "backorder.proposed"))
    assert [e["event"] for e in heard["staff"]] == ["backorder.proposed"]
    assert heard["shop"] == []


def test_sales_staff_limited_to_their_shops(world):
    sales = make_staff_in(world["t"], "SALES")
    mine = make_shop(world["t"], "9876500097")
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=mine.pk).update(salesperson=sales)
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    limited = _ticket(client_for(world["t"], sales))
    everyone = _ticket(client_for(world["t"], world["owner"]))
    place(world["t"], world["shop"], (world["product"], "1"))
    place(world["t"], mine, (world["product"], "1"))
    heard = listen({"sales": limited, "owner": everyone}, _event_ids(world["t"], "order.placed"))
    assert [e["retailer"] for e in heard["sales"]] == [str(mine.pk)]
    assert len(heard["owner"]) == 2
