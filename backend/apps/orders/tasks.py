"""Order tasks (thin). ``push_live`` is the outbox → WebSocket bridge (PLAN task 4.6): at least
once, and harmless when repeated, since clients only refetch."""

from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer

from apps.retailers.models import Retailer
from common.live import orders_group, shop_group
from common.models import OutboxEvent
from common.task_base import TenantTask

# Every order and backorder event staff see live; shops see all but the internal ones.
LIVE_EVENTS = (
    "order.placed",
    "order.on_hold",
    "order.hold_approved",
    "order.accepted",
    "order.rejected",
    "order.cancelled",
    "order.modified",
    "order.short_supplied",
    "order.dispatched",
    "order.delivered",
    "order.completed",
    "backorder.proposed",
    "backorder.skipped_credit",
    "backorder.allocated",
    "backorder.cancelled",
    "backorder.repriced_cancelled",
)
STAFF_ONLY = {"backorder.proposed", "backorder.skipped_credit"}


@shared_task(
    name="orders.push_live",
    base=TenantTask,
    bind=True,
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    max_retries=5,
)
def push_live(self: Any, *, event_id: str, tenant_id: str) -> bool:
    event = OutboxEvent.objects.filter(pk=event_id).first()
    if event is None or event.aggregate_type != "Order":
        return False
    payload = event.payload
    retailer_id = payload.get("retailer_id")
    shop = (
        Retailer.objects.filter(pk=retailer_id).values("shop_name", "salesperson_id").first()
        if retailer_id
        else None
    )
    data = {
        "type": "order",
        "event": event.event_type,
        "order": payload.get("order_id"),
        "number": payload.get("number"),
        "status": payload.get("status"),
    }
    layer = get_channel_layer()
    if layer is None:
        return False
    send = async_to_sync(layer.group_send)
    send(
        orders_group(UUID(tenant_id)),
        {
            "type": "live.event",
            "data": {
                **data,
                "retailer": retailer_id,
                "retailer_name": shop["shop_name"] if shop else "",
                "salesperson_id": str(shop["salesperson_id"])
                if shop and shop["salesperson_id"]
                else None,
            },
        },
    )
    if retailer_id and event.event_type not in STAFF_ONLY:
        send(shop_group(retailer_id), {"type": "live.event", "data": data})
    return True
