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
        "einvoices/<uuid:record_id>/cancel/", v.EInvoiceCancelView.as_view(), name="einvoice-cancel"
    ),
    path(
        "einvoices/<uuid:record_id>/reissue-preview/",
        v.EInvoiceReissuePreviewView.as_view(),
        name="einvoice-reissue-preview",
    ),
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
    path("ewaybills/", v.EWayBillListView.as_view(), name="ewaybills"),
    path("ewaybills/counts/", v.EWayBillCountsView.as_view(), name="ewaybill-counts"),
    path("ewaybills/<uuid:ewaybill_id>/", v.EWayBillDetailView.as_view(), name="ewaybill"),
    path(
        "ewaybills/<uuid:ewaybill_id>/part-b/",
        v.EWayBillPartBView.as_view(),
        name="ewaybill-part-b",
    ),
    path(
        "ewaybills/<uuid:ewaybill_id>/cancel/",
        v.EWayBillCancelView.as_view(),
        name="ewaybill-cancel",
    ),
    path(
        "invoices/<uuid:invoice_id>/ewaybill/",
        v.InvoiceEWayBillView.as_view(),
        name="invoice-ewaybill",
    ),
]
