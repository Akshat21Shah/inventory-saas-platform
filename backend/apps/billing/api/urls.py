from django.urls import path

from apps.billing.api import views as v

urlpatterns = [
    path("invoices/", v.InvoiceListView.as_view(), name="invoices"),
    path("invoices/<uuid:invoice_id>/", v.InvoiceDetailView.as_view(), name="invoice"),
    path("invoices/<uuid:invoice_id>/pdf/", v.InvoicePdfView.as_view(), name="invoice-pdf"),
    path(
        "invoices/<uuid:invoice_id>/regenerate-pdf/",
        v.InvoiceRegeneratePdfView.as_view(),
        name="invoice-regenerate-pdf",
    ),
    path("credit-notes/", v.CreditNoteListCreateView.as_view(), name="credit-notes"),
    path("credit-notes/<uuid:note_id>/", v.CreditNoteDetailView.as_view(), name="credit-note"),
    path("credit-notes/<uuid:note_id>/pdf/", v.CreditNotePdfView.as_view(), name="credit-note-pdf"),
    path(
        "credit-notes/<uuid:note_id>/regenerate-pdf/",
        v.CreditNoteRegeneratePdfView.as_view(),
        name="credit-note-regenerate-pdf",
    ),
    path("return-requests/", v.ReturnRequestListView.as_view(), name="return-requests"),
    path(
        "return-requests/<uuid:request_id>/",
        v.ReturnRequestDetailView.as_view(),
        name="return-request",
    ),
    path(
        "return-requests/<uuid:request_id>/approve/",
        v.ReturnRequestApproveView.as_view(),
        name="return-request-approve",
    ),
    path(
        "return-requests/<uuid:request_id>/reject/",
        v.ReturnRequestRejectView.as_view(),
        name="return-request-reject",
    ),
    path("settings/document-series/", v.DocumentSeriesView.as_view(), name="document-series"),
    path(
        "orders/<uuid:order_id>/confirmation/",
        v.OrderConfirmationView.as_view(),
        name="order-confirmation",
    ),
]
