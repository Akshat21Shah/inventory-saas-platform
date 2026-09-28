from django.urls import path

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
]
