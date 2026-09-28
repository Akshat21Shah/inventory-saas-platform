from django.urls import path

from apps.ledger.api import views as v

urlpatterns = [
    path("receivables/", v.ReceivablesView.as_view(), name="receivables"),
    path("receivables/ageing/", v.AgeingView.as_view(), name="receivables-ageing"),
    path("receivables/summary/", v.ReceivablesSummaryView.as_view(), name="receivables-summary"),
    path(
        "retailers/<uuid:retailer_id>/ledger/",
        v.RetailerLedgerView.as_view(),
        name="retailer-ledger",
    ),
    path("retailers/<uuid:retailer_id>/dues/", v.RetailerDuesView.as_view(), name="retailer-dues"),
    path("ledger/adjustments/", v.AdjustmentsView.as_view(), name="ledger-adjustments"),
]
