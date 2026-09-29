from django.urls import path

from apps.compliance.api import views as v

urlpatterns = [
    path("settings/gst-credentials/", v.GstCredentialsView.as_view(), name="gst-credentials"),
    path(
        "settings/gst-credentials/verify/",
        v.GstCredentialsVerifyView.as_view(),
        name="gst-credentials-verify",
    ),
    path("einvoices/", v.EInvoiceListView.as_view(), name="einvoices"),
    path("einvoices/counts/", v.EInvoiceCountsView.as_view(), name="einvoice-counts"),
    path("einvoices/<uuid:record_id>/", v.EInvoiceDetailView.as_view(), name="einvoice"),
    path(
        "invoices/<uuid:invoice_id>/einvoice/",
        v.InvoiceEInvoiceView.as_view(),
        name="invoice-einvoice",
    ),
    path(
        "credit-notes/<uuid:note_id>/einvoice/",
        v.CreditNoteEInvoiceView.as_view(),
        name="credit-note-einvoice",
    ),
]
