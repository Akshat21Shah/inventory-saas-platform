from django.urls import path

from apps.orders.api import staff_cart as c
from apps.orders.api import views as v

urlpatterns = [
    path("orders/", v.OrderListCreateView.as_view(), name="orders"),
    path("orders/counts/", v.OrderCountsView.as_view(), name="orders-counts"),
    path("orders/<uuid:order_id>/", v.OrderDetailView.as_view(), name="order"),
    path("orders/<uuid:order_id>/accept/", v.OrderAcceptView.as_view(), name="order-accept"),
    path("orders/<uuid:order_id>/reject/", v.OrderRejectView.as_view(), name="order-reject"),
    path("orders/<uuid:order_id>/cancel/", v.OrderCancelView.as_view(), name="order-cancel"),
    path("orders/<uuid:order_id>/lines/", v.OrderLinesView.as_view(), name="order-lines"),
    path(
        "orders/<uuid:order_id>/hold/approve/",
        v.HoldApproveView.as_view(),
        name="order-hold-approve",
    ),
    path(
        "orders/<uuid:order_id>/hold/reject/", v.HoldRejectView.as_view(), name="order-hold-reject"
    ),
    path(
        "order-lines/<uuid:line_id>/cancel-backorder/",
        v.CancelBackorderView.as_view(),
        name="order-line-cancel-backorder",
    ),
    path("fulfilments/", v.FulfilmentListView.as_view(), name="fulfilments"),
    path("fulfilments/<uuid:fulfilment_id>/", v.FulfilmentDetailView.as_view(), name="fulfilment"),
    path("fulfilments/<uuid:fulfilment_id>/pack/", v.PackView.as_view(), name="fulfilment-pack"),
    path(
        "fulfilments/<uuid:fulfilment_id>/dispatch/",
        v.DispatchView.as_view(),
        name="fulfilment-dispatch",
    ),
    path(
        "fulfilments/<uuid:fulfilment_id>/deliver/",
        v.DeliverView.as_view(),
        name="fulfilment-deliver",
    ),
    path(
        "fulfilments/<uuid:fulfilment_id>/cancel/",
        v.CancelShipmentView.as_view(),
        name="fulfilment-cancel",
    ),
    path("backorders/", v.BackorderQueueView.as_view(), name="backorders"),
    path("backorders/allocate/", v.AllocateView.as_view(), name="backorders-allocate"),
    path("backorders/allocations/", v.AllocationListView.as_view(), name="backorder-allocations"),
    path(
        "backorders/allocations/confirm/",
        v.ConfirmAllocationsView.as_view(),
        name="backorder-allocations-confirm",
    ),
    path(
        "backorders/allocations/<uuid:allocation_id>/reject/",
        v.RejectAllocationView.as_view(),
        name="backorder-allocation-reject",
    ),
    path(
        "backorders/<uuid:product_id>/", v.BackorderProductView.as_view(), name="backorder-product"
    ),
    path("retailers/<uuid:retailer_id>/cart/", c.StaffCartView.as_view(), name="retailer-cart"),
    path(
        "retailers/<uuid:retailer_id>/cart/lines/<uuid:product_id>/",
        c.StaffCartLineView.as_view(),
        name="retailer-cart-line",
    ),
    path(
        "retailers/<uuid:retailer_id>/cart/reduce-to-available/",
        c.StaffCartReduceView.as_view(),
        name="retailer-cart-reduce",
    ),
]
