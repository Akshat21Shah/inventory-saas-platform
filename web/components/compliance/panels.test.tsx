import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InvoiceDetailPage, InvoicesPage } from "@/components/billing/invoices";
import type {
  EInvoiceSummary,
  EWayBillRow,
  EWayBillSummary,
  InvoiceDetail,
  ReissuePreview,
} from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { FailedEWayBillsAlert } from "./dashboard";
import { EInvoicesPage } from "./lists";

const features = new Set<string>();
const permissions = new Set<string>();
const auth = {
  me: { id: "u1", tenant: { id: "t1" } },
  can: (p: string) => permissions.has(p),
  feature: (f: string) => features.has(f),
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/manage/invoices/i1",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  features.clear();
  permissions.clear();
});

const irn = (over: Partial<EInvoiceSummary> = {}): EInvoiceSummary => ({
  id: "e1",
  status: "GENERATED",
  irn: "a1b2c3".repeat(10) + "d4e5",
  ack_no: "112010036563310",
  ack_date: "2026-09-30T05:00:00Z",
  error_code: "",
  error_message: "",
  retryable: false,
  attempts: 1,
  requested_at: "2026-09-30T04:59:00Z",
  next_retry_at: null,
  generated_at: "2026-09-30T05:00:00Z",
  report_by: null,
  past_report_by: false,
  can_request: false,
  can_cancel: true,
  cancel_blocked: null,
  cancel_until: "2026-10-01T05:00:00Z",
  cancel_reason_code: "",
  cancel_remarks: "",
  cancel_outcome: "",
  cancel_error: "",
  cancelled_at: null,
  reissued_invoice: null,
  ...over,
});

const bill = (over: Partial<EWayBillSummary> = {}): EWayBillSummary => ({
  id: "w1",
  status: "FAILED",
  ewb_number: "",
  ewb_date: null,
  valid_until: null,
  consignment_value: "120000.00",
  transport_mode: "ROAD",
  vehicle_number: "MH12AB1234",
  transporter_id: "",
  transporter_name: "Speedy Roadways",
  transport_doc_no: "LR-1",
  transport_doc_date: null,
  distance_km: null,
  error_code: "VALIDATION",
  error_message: "Enter the distance (1 to 4,000 km).",
  retryable: false,
  attempts: 1,
  requested_at: "2026-09-30T05:00:00Z",
  next_retry_at: null,
  generated_at: null,
  cancelled_at: null,
  can_request: true,
  can_update: false,
  can_cancel: false,
  cancel_until: null,
  pending_update: "",
  last_update_error: "",
  ...over,
});

const invoice = (over: Partial<InvoiceDetail> = {}): InvoiceDetail => ({
  id: "i1",
  number: "INV/26-27/000001",
  invoice_date: "2026-09-30",
  due_date: "2026-10-30",
  retailer: { id: "r1", code: "R-00001", shop_name: "Kaveri Traders" },
  order: { id: "o1", number: "ORD-2026-000001" },
  grand_total: "120000.00",
  balance_due: "120000.00",
  payment_status: "UNPAID",
  days_overdue: 0,
  issued_trigger: "ON_DISPATCH",
  rate_differs_from_order: false,
  pdf_status: "READY",
  einvoice_status: "GENERATED",
  status: "ISSUED",
  seller: {},
  buyer: { gstin: "27AAACK1234C1Z5" },
  place_of_supply: { code: "27", name: "Maharashtra" },
  supply_type: "INTRA",
  prices_include_tax: false,
  reverse_charge: false,
  totals: {
    gross_total: "114285.71",
    discount_total: "0.00",
    taxable_total: "114285.71",
    cgst_total: "2857.14",
    sgst_total: "2857.14",
    igst_total: "0.00",
    cess_total: "0.00",
    round_off: "0.01",
    grand_total: "120000.00",
  },
  amount_in_words: "Rupees One Lakh Twenty Thousand Only",
  amount_paid: "0.00",
  amount_credited: "0.00",
  settings_snapshot: {},
  fulfilment_id: "f1",
  lines: [],
  credit_notes: [],
  applied: [],
  irn: "",
  ack_no: "",
  ack_date: null,
  einvoice: irn(),
  ewaybill: null,
  ...over,
});

const preview = (over: Partial<ReissuePreview> = {}): ReissuePreview => ({
  buyer: { name: "Kaveri Traders", gstin: "27AAACK1234C1Z5", state_code: "27" },
  buyer_changed: true,
  supply_type: "INTRA",
  supply_type_before: "INTRA",
  rate_changes: [],
  ...over,
});

function manageCompliance() {
  features.add("einvoice");
  features.add("ewaybill");
  permissions.add("compliance.manage");
  permissions.add("invoices.manage");
}

describe("An invoice's IRN", () => {
  it("names the portal's refusal and tries again", async () => {
    manageCompliance();
    const user = userEvent.setup();
    const failed = irn({
      status: "FAILED",
      irn: "",
      ack_no: "",
      ack_date: null,
      error_message: "The buyer's GSTIN is not active.",
      can_request: true,
      can_cancel: false,
      report_by: "2026-10-30",
    });
    const calls = mockApi({
      "/api/v1/invoices/i1/": () => [200, invoice({ einvoice: failed })],
      "POST /api/v1/invoices/i1/einvoice/": () => [200, failed],
    });
    renderWithIntl(<InvoiceDetailPage invoiceId="i1" />);
    const panel = await screen.findByRole("region", { name: "E-invoice (IRN)" });
    expect(within(panel).getByText("IRN failed")).toBeVisible();
    expect(within(panel).getByRole("alert")).toHaveTextContent(
      "The GST portal refused it: The buyer's GSTIN is not active.",
    );
    expect(within(panel).getByText(/Must get its IRN by/)).toBeVisible();
    await user.click(within(panel).getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(
        calls.some((c) => c.method === "POST" && c.path === "/api/v1/invoices/i1/einvoice/"),
      ).toBe(true),
    );
  });

  it("says what to do first when a live e-way bill is in the way", async () => {
    manageCompliance();
    const blocked = irn({
      can_cancel: false,
      cancel_blocked: {
        reason: "EWAY_BILL",
        message: "Cancel e-way bill 331000000001 first, then cancel the IRN.",
        ewaybill_id: "w1",
      },
    });
    mockApi({
      "/api/v1/invoices/i1/": () => [
        200,
        invoice({
          einvoice: blocked,
          ewaybill: bill({
            status: "GENERATED",
            ewb_number: "331000000001",
            error_message: "",
            can_request: false,
            can_update: true,
            can_cancel: true,
            cancel_until: "2026-10-01T05:00:00Z",
          }),
        }),
      ],
    });
    renderWithIntl(<InvoiceDetailPage invoiceId="i1" />);
    expect(
      await screen.findByText(/Cancel e-way bill 331000000001 first, then cancel the IRN./),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Go to the e-way bill" })).toHaveAttribute(
      "href",
      "#ewaybill",
    );
    expect(screen.queryByRole("button", { name: "Cancel IRN" })).toBeNull();
    const panel = screen.getByRole("region", { name: "E-way bill" });
    expect(within(panel).getByRole("button", { name: "Change vehicle" })).toBeVisible();
    expect(within(panel).getByRole("button", { name: "Cancel e-way bill" })).toBeVisible();
  });

  it("re-issues only after staff confirm keeping the original GST rates", async () => {
    manageCompliance();
    const user = userEvent.setup();
    const calls = mockApi({
      "/api/v1/invoices/i1/": () => [200, invoice()],
      "/api/v1/einvoices/e1/reissue-preview/": () => [
        200,
        preview({
          rate_changes: [
            {
              line_no: 1,
              description: "Assam tea 250 g",
              hsn_code: "0902",
              original_rate: "5.000",
              today_rate: "12.000",
            },
          ],
        }),
      ],
      "POST /api/v1/einvoices/e1/cancel/": () => [200, irn({ status: "CANCELLING" })],
    });
    renderWithIntl(<InvoiceDetailPage invoiceId="i1" />);
    await user.click(await screen.findByRole("button", { name: "Cancel IRN" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText("Assam tea 250 g: original 5%, today 12%"),
    ).toBeVisible();
    expect(within(dialog).getByText(/details changed since/)).toBeVisible();
    const confirm = within(dialog).getByRole("button", { name: "Cancel IRN" });
    expect(confirm).toBeDisabled();
    await user.click(
      within(dialog).getByRole("checkbox", { name: "Keep the original rates on the new invoice" }),
    );
    await user.click(confirm);
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/einvoices/e1/cancel/")?.body).toEqual({
        reason_code: "DATA_ENTRY_MISTAKE",
        remarks: "",
        outcome: "REISSUE",
        to_backorder: false,
        confirm_rate_changes: true,
      }),
    );
  });

  it("takes the goods back to wait on backorder", async () => {
    manageCompliance();
    const user = userEvent.setup();
    const calls = mockApi({
      "/api/v1/invoices/i1/": () => [200, invoice()],
      "/api/v1/einvoices/e1/reissue-preview/": () => [200, preview()],
      "POST /api/v1/einvoices/e1/cancel/": () => [200, irn({ status: "CANCELLING" })],
    });
    renderWithIntl(<InvoiceDetailPage invoiceId="i1" />);
    await user.click(await screen.findByRole("button", { name: "Cancel IRN" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("radio", { name: /Take the goods back/ }));
    await user.click(within(dialog).getByRole("button", { name: "Cancel IRN" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/einvoices/e1/cancel/")?.body).toMatchObject({
        outcome: "TAKE_BACK",
        to_backorder: true,
        confirm_rate_changes: false,
      }),
    );
  });

  it("shows a cancelled invoice with its re-issue, and offers no credit note", async () => {
    manageCompliance();
    mockApi({
      "/api/v1/invoices/i1/": () => [
        200,
        invoice({
          status: "CANCELLED",
          einvoice_status: "CANCELLED",
          einvoice: irn({
            status: "CANCELLED",
            can_cancel: false,
            cancelled_at: "2026-09-30T08:00:00Z",
            cancel_outcome: "REISSUE",
            reissued_invoice: { id: "i2", number: "INV/26-27/000002" },
          }),
        }),
      ],
    });
    renderWithIntl(<InvoiceDetailPage invoiceId="i1" />);
    expect(await screen.findByText(/This invoice is cancelled/)).toBeVisible();
    for (const link of screen.getAllByRole("link", { name: "Re-issued as INV/26-27/000002" })) {
      expect(link).toHaveAttribute("href", "/manage/invoices/i2");
    }
    expect(screen.queryByRole("link", { name: /Credit note/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Make e-way bill" })).toBeNull();
  });

  it("shows nothing about IRNs or e-way bills while the modules are off", async () => {
    permissions.add("compliance.manage");
    mockApi({ "/api/v1/invoices/i1/": () => [200, invoice({ einvoice: null })] });
    renderWithIntl(<InvoiceDetailPage invoiceId="i1" />);
    expect(await screen.findByText("Invoice INV/26-27/000001")).toBeVisible();
    expect(screen.queryByRole("region", { name: "E-invoice (IRN)" })).toBeNull();
    expect(screen.queryByRole("region", { name: "E-way bill" })).toBeNull();
  });
});

describe("An invoice's e-way bill", () => {
  it("tries a failed one again with the corrected details", async () => {
    manageCompliance();
    const user = userEvent.setup();
    const calls = mockApi({
      "/api/v1/invoices/i1/": () => [200, invoice({ ewaybill: bill() })],
      "POST /api/v1/invoices/i1/ewaybill/": () => [200, bill({ status: "SUBMITTED" })],
    });
    renderWithIntl(<InvoiceDetailPage invoiceId="i1" />);
    const panel = await screen.findByRole("region", { name: "E-way bill" });
    expect(within(panel).getByRole("alert")).toHaveTextContent(
      "The e-way bill portal refused it: Enter the distance (1 to 4,000 km).",
    );
    await user.click(within(panel).getByRole("button", { name: "Try again" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/^Vehicle number/)).toHaveValue("MH12AB1234");
    await user.type(within(dialog).getByLabelText(/^Distance/), "850");
    await user.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/invoices/i1/ewaybill/")?.body).toEqual({
        transport_mode: "ROAD",
        vehicle_number: "MH12AB1234",
        transporter_id: "",
        transporter_name: "Speedy Roadways",
        transport_doc_no: "LR-1",
        transport_doc_date: null,
        distance_km: 850,
      }),
    );
  });

  it("puts the server's refusal on the field", async () => {
    manageCompliance();
    const user = userEvent.setup();
    mockApi({
      "/api/v1/invoices/i1/": () => [200, invoice({ ewaybill: null })],
      "POST /api/v1/invoices/i1/ewaybill/": () => [
        400,
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "",
            details: { fields: { invoice: ["This invoice already has an e-way bill."] } },
          },
        },
      ],
    });
    renderWithIntl(<InvoiceDetailPage invoiceId="i1" />);
    await user.click(await screen.findByRole("button", { name: "Make e-way bill" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Make e-way bill" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "This invoice already has an e-way bill.",
    );
  });
});

describe("Lists and the dashboard", () => {
  const failedRow: EWayBillRow = {
    ...bill(),
    invoice_id: "i1",
    invoice_number: "INV/26-27/000001",
    invoice_date: "2026-09-30",
    shop_name: "Kaveri Traders",
    retailer_id: "r1",
    shipment_number: "SHP-2026-000001",
    updates: [],
  };

  it("keeps failed e-way bills at the top of the dashboard until they're fixed", async () => {
    manageCompliance();
    const calls = mockApi({
      "/api/v1/ewaybills/": () => [200, { next: null, previous: null, results: [failedRow] }],
      "/api/v1/ewaybills/counts/": () => [200, { pending: 0, failed: 1 }],
    });
    renderWithIntl(<FailedEWayBillsAlert />);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("1 e-way bill failed")).toBeVisible();
    expect(within(alert).getByText("Shipment SHP-2026-000001 · Kaveri Traders")).toBeVisible();
    expect(within(alert).getByText("Vehicle MH12AB1234")).toBeVisible();
    expect(within(alert).getByText("Enter the distance (1 to 4,000 km).")).toBeVisible();
    expect(within(alert).getByRole("link", { name: "Fix and try again" })).toHaveAttribute(
      "href",
      "/manage/invoices/i1#ewaybill",
    );
    expect(calls[0]!.url.searchParams.get("needs_action")).toBe("true");
  });

  it("asks nothing on the dashboard while e-way bills are off", async () => {
    permissions.add("compliance.manage");
    const calls = mockApi({});
    const { container } = renderWithIntl(<FailedEWayBillsAlert />);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(container).toBeEmptyDOMElement();
    expect(calls).toEqual([]);
  });

  it("lists e-invoices while the module is on", async () => {
    manageCompliance();
    mockApi({
      "/api/v1/einvoices/": () => [
        200,
        {
          next: null,
          previous: null,
          results: [
            {
              ...irn({ status: "FAILED", error_message: "Invalid HSN code." }),
              document_type: "INVOICE",
              document_id: "i1",
              document_number: "INV/26-27/000001",
              document_date: "2026-09-30",
              shop_name: "Kaveri Traders",
              retailer_id: "r1",
              grand_total: "120000.00",
              invoice_id: "i1",
            },
          ],
        },
      ],
    });
    renderWithIntl(<EInvoicesPage />);
    const links = await screen.findAllByRole("link", { name: "Invoice INV/26-27/000001" });
    expect(links[0]).toHaveAttribute("href", "/manage/invoices/i1#einvoice");
    expect(screen.getAllByText("Invalid HSN code.")[0]).toBeVisible();
  });

  it("says e-invoices are off, asking nothing", async () => {
    const calls = mockApi({});
    renderWithIntl(<EInvoicesPage />);
    expect(await screen.findByText("E-invoices aren't switched on")).toBeVisible();
    expect(calls).toEqual([]);
  });

  it("adds the e-invoice column to the invoices list only while the module is on", async () => {
    const row = { ...invoice(), einvoice_status: "FAILED" as const };
    mockApi({ "/api/v1/invoices/": () => [200, { next: null, previous: null, results: [row] }] });
    const { unmount } = renderWithIntl(<InvoicesPage />);
    expect(await screen.findAllByText("INV/26-27/000001")).not.toHaveLength(0);
    expect(screen.queryByText("IRN failed")).toBeNull();
    expect(screen.queryByRole("link", { name: "E-invoices" })).toBeNull();
    unmount();
    manageCompliance();
    renderWithIntl(<InvoicesPage />);
    expect((await screen.findAllByText("IRN failed"))[0]).toBeVisible();
    expect(screen.getByRole("link", { name: "E-invoices" })).toHaveAttribute(
      "href",
      "/manage/invoices/einvoices",
    );
  });
});
