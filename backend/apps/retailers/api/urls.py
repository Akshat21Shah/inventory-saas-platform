from django.urls import path

from apps.retailers.api import views as v

urlpatterns = [
    path("retailers/", v.RetailerListCreateView.as_view(), name="retailers"),
    path("retailers/bulk/", v.RetailerBulkView.as_view(), name="retailers-bulk"),
    path("retailers/salespeople/", v.SalespeopleView.as_view(), name="retailers-salespeople"),
    path("retailers/<uuid:retailer_id>/", v.RetailerDetailView.as_view(), name="retailer-detail"),
    path(
        "retailers/<uuid:retailer_id>/credit/",
        v.RetailerCreditView.as_view(),
        name="retailer-credit",
    ),
    path(
        "retailers/<uuid:retailer_id>/block/", v.RetailerBlockView.as_view(), name="retailer-block"
    ),
    path(
        "retailers/<uuid:retailer_id>/unblock/",
        v.RetailerUnblockView.as_view(),
        name="retailer-unblock",
    ),
    path(
        "retailers/<uuid:retailer_id>/resend-welcome/",
        v.RetailerWelcomeView.as_view(),
        name="retailer-resend-welcome",
    ),
    path(
        "retailers/<uuid:retailer_id>/addresses/",
        v.RetailerAddressesView.as_view(),
        name="retailer-addresses",
    ),
    path(
        "retailers/<uuid:retailer_id>/addresses/<uuid:address_id>/",
        v.RetailerAddressDetailView.as_view(),
        name="retailer-address-detail",
    ),
]
