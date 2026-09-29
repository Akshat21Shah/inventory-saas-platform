from django.urls import path

from apps.payments.api import gateway as g
from apps.payments.api import views as v

urlpatterns = [
    path("payments/", v.PaymentListCreateView.as_view(), name="payments"),
    path("payments/collect/", v.CollectView.as_view(), name="payments-collect"),
    path("payments/handover/", v.HandoverView.as_view(), name="payments-handover"),
    path("payments/<uuid:payment_id>/", v.PaymentDetailView.as_view(), name="payment"),
    path("payments/<uuid:payment_id>/allocate/", v.AllocateView.as_view(), name="payment-allocate"),
    path("payments/<uuid:payment_id>/clear/", v.ClearView.as_view(), name="payment-clear"),
    path("payments/<uuid:payment_id>/bounce/", v.BounceView.as_view(), name="payment-bounce"),
    path("payments/<uuid:payment_id>/reverse/", v.ReverseView.as_view(), name="payment-reverse"),
    path("payments/<uuid:payment_id>/receipt/", v.ReceiptView.as_view(), name="payment-receipt"),
    path(
        "payments/<uuid:payment_id>/regenerate-receipt/",
        v.ReceiptRegenerateView.as_view(),
        name="payment-regenerate-receipt",
    ),
    path("refunds/", v.RefundListCreateView.as_view(), name="refunds"),
    path("refunds/<uuid:refund_id>/", v.RefundDetailView.as_view(), name="refund"),
    path("refunds/<uuid:refund_id>/voucher/", v.RefundVoucherView.as_view(), name="refund-voucher"),
    path("refunds/<uuid:refund_id>/reverse/", v.RefundReverseView.as_view(), name="refund-reverse"),
    path(
        "refunds/<uuid:refund_id>/regenerate-voucher/",
        v.RefundRegenerateVoucherView.as_view(),
        name="refund-regenerate-voucher",
    ),
    path(
        "reports/collections-pending-handover/",
        v.PendingHandoverView.as_view(),
        name="collections-pending-handover",
    ),
    path(
        "payment-allocations/<uuid:allocation_id>/reverse/",
        v.AllocationReverseView.as_view(),
        name="payment-allocation-reverse",
    ),
    path("settings/payment-gateway/", g.GatewaySettingsView.as_view(), name="payment-gateway"),
    path(
        "settings/payment-gateway/verify/",
        g.GatewayVerifyView.as_view(),
        name="payment-gateway-verify",
    ),
]
