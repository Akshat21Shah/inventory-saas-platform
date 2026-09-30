import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { InvoiceDetail, InvoiceRow } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { NewCreditNotePage } from "./credit-notes";
import { DocumentButton } from "./document-button";
import { InvoiceDetailPage, InvoicesPage } from "./invoices";

const permissions = new Set<string>();
const features = new Set<string>();
const auth = {
  me: { id: "u1", tenant: { id: "t1" } },
  can: (p: string) => permissions.has(p),
  feature: (f: string) => features.has(f),
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const router = { push: vi.fn(), replace: vi.fn(), back: vi.fn() };
let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/manage/invoices",
  useSearchParams: () => search,
}));

afterEach(() => {
  vi.unstubAllGlobals();
  permissions.clear();
  features.clear();
  router.push.mockReset();
  search = new URLSearchParams();
});

const row: InvoiceRow = {
  id: "i1",
  number: "INV/26-27/000001",
  invoice_date: "2026-08-01",
  due_date: "2026-08-31",
  retailer: { id: "r1", code: "R-00001", shop_name: "Ganesh Kirana" },
  order: { id: "o1", number: "ORD-2026-000001" },
  grand_total: "1296.00",
  balance_due: "296.00",
  payment_status: "PARTIAL",
  days_overdue: 28,
  issued_trigger: "ON_DISPATCH",
  rate_differs_from_order: false,
  pdf_status: "READY",
  einvoice_status: "NOT_APPLICABLE",
  status: "ISSUED",
};

const detail: InvoiceDetail = {
  ...row,
  rate_differs_from_order: true,
  seller: {},
  buyer: {},
  place_of_supply: { code: "27", name: "Maharashtra" },
  supply_type: "INTRA",
  prices_include_tax: false,
  reverse_charge: false,
  totals: {
    gross_total: "1234.50",
    discount_total: "0.00",
    taxable_total: "1234.50",
    cgst_total: "30.86",
    sgst_total: "30.86",
    igst_total: "0.00",
    cess_total: "0.00",
    round_off: "-0.22",
    grand_total: "1296.00",
  },
  amount_in_words: "Rupees One Thousand Two Hundred Ninety Six Only",
  amount_paid: "1000.00",
  amount_credited: "0.00",
  settings_snapshot: {},
  fulfilment_id: "f1",
  lines: [
    {
      id: "l1",
      line_no: 1,
      product_id: "p1",
      product_code: "A",
      description: "Assam tea 250 g",
      hsn_code: "0902",
      unit_code: "PCS",
      quantity: "10.000",
      unit_price: "123.45",
      gross_amount: "1234.50",
      discount_amount: "0.00",
      taxable_value: "1234.50",
      gst_rate: "5.000",
      cgst_rate: "2.500",
      cgst_amount: "30.86",
      sgst_rate: "2.500",
      sgst_amount: "30.86",
      igst_rate: "0.000",
      igst_amount: "0.00",
      cess_rate: "0.000",
      cess_amount: "0.00",
      line_total: "1296.22",
      order_rate: "12.000",
      rate_differs_from_order: true,
      credited_quantity: "3.000",
    },
  ],
  credit_notes: [],
  applied: [
    {
      id: "a1",
      source_type: "PAYMENT",
      source_id: "pay1",
      source_number: "RCT/26-27/000001",
      amount: "1000.00",
      automatic: true,
      reversed: false,
      created_at: "2026-09-01T10:00:00Z",
    },
  ],
  irn: "",
  ack_no: "",
  ack_date: null,
  einvoice: null,
  ewaybill: null,
};

describe("Invoices", () => {
  it("lists invoices with what is still owed and how late it is", async () => {
    const calls = mockApi({
      "/api/v1/invoices/": () => [200, { next: null, previous: null, results: [row] }],
    });
    renderWithIntl(<InvoicesPage />);
    expect(await screen.findAllByText("INV/26-27/000001")).not.toHaveLength(0);
    expect(screen.getAllByText("28 days overdue")[0]).toBeVisible();
    await userEvent.setup().click(screen.getAllByLabelText("Overdue only")[0]!);
    await waitFor(() => expect(calls.at(-1)!.url.searchParams.get("overdue")).toBe("true"));
  });

  it("shows the rate warning, the money applied and offers a credit note", async () => {
    permissions.add("invoices.manage");
    mockApi({ "/api/v1/invoices/i1/": () => [200, detail] });
    renderWithIntl(<InvoiceDetailPage invoiceId="i1" />);
    expect(await screen.findByText(/GST rate on some items changed/)).toBeVisible();
    expect(screen.getByText("Payment RCT/26-27/000001")).toBeVisible();
    expect(screen.getByText(/ordered at 12%/)).toBeVisible();
    expect(screen.getByText(/3 credited/)).toBeVisible();
    expect(screen.getByRole("link", { name: /Credit note/ })).toHaveAttribute(
      "href",
      "/manage/invoices/credit-notes/new?invoice=i1",
    );
  });
});

describe("Documents", () => {
  it("opens the signed link, or says the PDF is being prepared", async () => {
    const opened = { location: { href: "" }, close: vi.fn() };
    vi.stubGlobal(
      "open",
      vi.fn(() => opened),
    );
    const user = userEvent.setup();
    const ready = vi.fn(async () => ({
      data: { status: "READY" as const, url: "https://files/x.pdf" },
      status: 200,
    }));
    const { unmount } = renderWithIntl(<DocumentButton fetchLink={ready}>Download</DocumentButton>);
    await user.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(opened.location.href).toBe("https://files/x.pdf"));
    unmount();
    const waiting = vi.fn(async () => ({
      data: { status: "PENDING" as const, url: null },
      status: 202,
    }));
    renderWithIntl(<DocumentButton fetchLink={waiting}>Download</DocumentButton>);
    await user.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(opened.close).toHaveBeenCalled());
  });
});

describe("New credit note", () => {
  it("sends the quantities, what happened to the goods and a reason, once per key", async () => {
    search = new URLSearchParams("invoice=i1");
    const calls = mockApi({
      "/api/v1/invoices/i1/": () => [200, detail],
      "POST /api/v1/credit-notes/": () => [201, { id: "cn1", number: "CN/26-27/000001" }],
    });
    const user = userEvent.setup();
    renderWithIntl(<NewCreditNotePage />);
    await user.type(await screen.findByLabelText("Quantity back"), "2");
    await user.click(screen.getByRole("button", { name: "Issue credit note" }));
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/manage/invoices/credit-notes/cn1"),
    );
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f]{32}$/);
    expect(post.body).toEqual({
      invoice: "i1",
      kind: "RETURN",
      reason: "DAMAGED",
      note: "",
      lines: [{ invoice_line: "l1", quantity: "2", disposition: "RETURN_TO_STOCK" }],
    });
  });

  it("switches to a price adjustment with a taxable value per line", async () => {
    search = new URLSearchParams("invoice=i1");
    const calls = mockApi({
      "/api/v1/invoices/i1/": () => [200, detail],
      "POST /api/v1/credit-notes/": () => [
        400,
        { error: { code: "VALIDATION_ERROR", message: "", details: { fields: { note: ["x"] } } } },
      ],
    });
    const user = userEvent.setup();
    renderWithIntl(<NewCreditNotePage />);
    await user.click(await screen.findByLabelText("Price adjustment (no goods move)"));
    await user.type(screen.getByLabelText("Taxable value to credit"), "100");
    await user.click(screen.getByRole("button", { name: "Issue credit note" }));
    expect(await screen.findByText("x")).toBeVisible(); // the note's error, from the server
    const post = calls.find((c) => c.method === "POST")!;
    expect((post.body as { kind: string }).kind).toBe("PRICE_ADJUSTMENT");
    expect((post.body as { lines: unknown[] }).lines).toEqual([
      { invoice_line: "l1", taxable_value: "100" },
    ]);
  });
});
