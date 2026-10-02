import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Dues, PaymentDetail, ReceivablesPage as Page } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { HandoverPage, NewPaymentPage, PaymentDetailPage, PaymentsPage } from "./payments";
import { ReceivablesPage } from "./receivables";
import { RefundDetailPage } from "./refunds";

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
  usePathname: () => "/manage/payments",
  useSearchParams: () => search,
}));

afterEach(() => {
  vi.unstubAllGlobals();
  permissions.clear();
  features.clear();
  router.push.mockReset();
  search = new URLSearchParams();
});

const shop = { id: "r1", code: "R-00001", shop_name: "Ganesh Kirana" };
const dues: Dues = {
  position: {
    balance: "389.00",
    owed: "389.00",
    overdue: "259.00",
    unapplied_credit: "0.00",
    oldest_due: "2026-08-01",
    days_overdue: 58,
  },
  credit_held_while_advances_off: null,
  financial_year_start: "2026-04-01",
  dues: [
    {
      kind: "INVOICE",
      id: "i1",
      number: "INV/26-27/000001",
      document_date: "2026-07-02",
      due_date: "2026-08-01",
      amount: "259.00",
      balance_due: "259.00",
    },
    {
      kind: "INVOICE",
      id: "i2",
      number: "INV/26-27/000002",
      document_date: "2026-09-01",
      due_date: "2026-10-01",
      amount: "130.00",
      balance_due: "130.00",
    },
  ],
  unused_money: [],
};

const payment: PaymentDetail = {
  id: "p1",
  number: "RCT/26-27/000001",
  payment_date: "2026-03-30",
  retailer: shop,
  amount: "500.00",
  mode: "CHEQUE",
  status: "RECEIVED",
  credit_timing: "ON_RECEIPT",
  credited: true,
  unapplied_amount: "111.00",
  reference_no: "",
  cheque_number: "004512",
  handover_status: "WITH_SALESMAN",
  collected_by_name: "Ravi",
  receipt_pdf_status: "READY",
  dated_in_previous_financial_year: true,
  held_as_credit_while_advances_off: "111.00",
  cheque_date: null,
  bank_name: "SBI",
  notes: "",
  recorded_by_name: "Ravi",
  handed_over_at: null,
  handed_over_by_name: "",
  cleared_at: null,
  reversed_at: null,
  reversal_reason: "",
  used_for: [
    {
      id: "a1",
      target_type: "INVOICE",
      target_id: "i1",
      target_number: "INV/26-27/000001",
      amount: "389.00",
      automatic: true,
      reversed: false,
      created_at: "2026-09-28T10:00:00Z",
    },
  ],
};

describe("Recording a payment", () => {
  it("pays the chosen bills first, with an Idempotency-Key, and warns about an earlier year", async () => {
    permissions.add("payments.record");
    search = new URLSearchParams("retailer=r1");
    const calls = mockApi({
      "/api/v1/retailers/r1/": () => [200, { ...shop, owner_name: "", mobile: "" }],
      "/api/v1/retailers/r1/dues/": () => [200, dues],
      "POST /api/v1/payments/": () => [201, { id: "p9", number: "RCT/26-27/000009" }],
    });
    const user = userEvent.setup();
    renderWithIntl(<NewPaymentPage />);
    expect(await screen.findByText(/Oldest bill 58 days overdue/)).toBeVisible();
    await user.type(screen.getByLabelText(/Amount/), "200");
    const date = screen.getByLabelText(/Payment date/);
    await user.clear(date);
    await user.type(date, "2026-03-30");
    expect(await screen.findByText(/earlier financial year/)).toBeVisible();
    await user.type(screen.getByLabelText(/INV\/26-27\/000002/), "130");
    await user.click(screen.getByRole("button", { name: "Record payment" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/manage/payments/p9"));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f]{32}$/);
    expect(post.body).toMatchObject({
      retailer: "r1",
      amount: "200",
      mode: "CASH",
      payment_date: "2026-03-30",
      pay_first: [{ target_type: "INVOICE", target_id: "i2", amount: "130" }],
    });
  });

  it("is a collection for sales staff, without choosing bills", async () => {
    permissions.add("payments.collect");
    search = new URLSearchParams("retailer=r1");
    const calls = mockApi({
      "/api/v1/retailers/r1/": () => [200, { ...shop, owner_name: "", mobile: "" }],
      "/api/v1/retailers/r1/dues/": () => [200, dues],
      "POST /api/v1/payments/collect/": () => [201, { id: "p9", number: "RCT/26-27/000009" }],
    });
    const user = userEvent.setup();
    renderWithIntl(<NewPaymentPage />);
    expect(await screen.findByText(/stays "With salesman"/)).toBeVisible();
    expect(screen.queryByText(/Pay these bills first/)).toBeNull();
    await user.type(screen.getByLabelText(/Amount/), "100");
    await user.click(screen.getByRole("button", { name: "Record collection" }));
    await waitFor(() => expect(router.push).toHaveBeenCalled());
    expect(calls.find((c) => c.method === "POST")!.path).toBe("/api/v1/payments/collect/");
  });

  it("shows the server's refusal in plain words", async () => {
    permissions.add("payments.record");
    search = new URLSearchParams("retailer=r1");
    mockApi({
      "/api/v1/retailers/r1/": () => [200, { ...shop, owner_name: "", mobile: "" }],
      "/api/v1/retailers/r1/dues/": () => [200, dues],
      "POST /api/v1/payments/": () => [
        400,
        { error: { code: "PAYMENT_EXCEEDS_OUTSTANDING", message: "", details: {} } },
      ],
    });
    const user = userEvent.setup();
    renderWithIntl(<NewPaymentPage />);
    await user.type(await screen.findByLabelText(/Amount/), "5000");
    await user.click(screen.getByRole("button", { name: "Record payment" }));
    expect(await screen.findByText(/more than the shop owes/)).toBeVisible();
  });
});

describe("A payment", () => {
  it("shows its notices and the actions the user may take", async () => {
    permissions.add("payments.record");
    mockApi({ "/api/v1/payments/p1/": () => [200, payment] });
    renderWithIntl(<PaymentDetailPage paymentId="p1" />);
    expect(await screen.findByText(/dated in an earlier financial year/)).toBeVisible();
    expect(
      screen.getByText(/₹111.00 is held as credit even though advances are off/),
    ).toBeVisible();
    for (const name of ["Mark handed over", "Cheque cleared", "Use the credit", "Move"]) {
      expect(screen.getByRole("button", { name })).toBeVisible();
    }
    expect(screen.queryByRole("button", { name: "Cheque bounced" })).toBeNull(); // payments.reverse
  });

  it("shows the charge added when the cheque bounced (ADR-057)", async () => {
    mockApi({
      "/api/v1/payments/p1/": () => [
        200,
        {
          ...payment,
          status: "BOUNCED",
          reversal_reason: "Insufficient funds",
          bounce_charge: "500.00",
        },
      ],
    });
    renderWithIntl(<PaymentDetailPage paymentId="p1" />);
    const label = await screen.findByText("Cheque bounce charge");
    expect(label.parentElement).toHaveTextContent("₹500.00");
  });
});

describe("Collections to hand over", () => {
  it("marks the selected collections handed over", async () => {
    permissions.add("payments.record");
    const calls = mockApi({
      "/api/v1/reports/collections-pending-handover/": () => [
        200,
        [
          {
            salesman_id: "s1",
            salesman_name: "Ravi",
            count: 1,
            amount: "500.00",
            oldest: "2026-09-28",
          },
        ],
      ],
      "/api/v1/payments/": () => [200, { next: null, previous: null, results: [payment] }],
      "POST /api/v1/payments/handover/": () => [200, { payments: [] }],
    });
    const user = userEvent.setup();
    renderWithIntl(<HandoverPage />);
    expect(await screen.findByText("Ravi", { selector: "p" })).toBeVisible();
    const boxes = await screen.findAllByRole("checkbox", { name: /Select RCT\/26-27\/000001/ });
    await user.click(boxes[0]!);
    const bar = screen.getAllByRole("region", { name: "Selected collections" })[0]!;
    await user.click(within(bar).getByRole("button", { name: "Mark handed over" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")!.body).toEqual({ payments: ["p1"] }),
    );
  });
});

describe("Collections to hand over, when there are none", () => {
  it("says so once", async () => {
    permissions.add("payments.record");
    mockApi({
      "/api/v1/reports/collections-pending-handover/": () => [200, []],
      "/api/v1/payments/": () => [200, { next: null, previous: null, results: [] }],
    });
    renderWithIntl(<HandoverPage />);
    expect(await screen.findByText("Nothing to hand over")).toBeVisible();
    await waitFor(() => expect(screen.getAllByText("Nothing to hand over")).toHaveLength(1));
    expect(screen.queryByRole("heading", { name: "With each salesman" })).toBeNull();
  });
});

describe("Receivables", () => {
  it("switches the ageing between days since the bill and days past due", async () => {
    permissions.add("ledger.view");
    const page = (basis: "INVOICE_DATE" | "DUE_DATE"): Page => ({
      basis,
      totals: {
        buckets: {
          not_due: "130.00",
          d0_30: "0.00",
          d31_60: "259.00",
          d61_90: "0.00",
          d90_plus: "0.00",
        },
        owed: "389.00",
        overdue: "259.00",
        unapplied_credit: "0.00",
        net: "389.00",
        shops: 1,
      },
      count: 1,
      page: 1,
      page_size: 50,
      results: [],
    });
    const calls = mockApi({
      "/api/v1/receivables/ageing/": (_b, url) => [
        200,
        page(url.searchParams.get("basis") === "DUE_DATE" ? "DUE_DATE" : "INVOICE_DATE"),
      ],
      "/api/v1/receivables/summary/": () => [
        200,
        {
          owed: "389.00",
          overdue: "259.00",
          shops_overdue: 1,
          due_this_week: "0.00",
          unapplied_credit: "0.00",
          collections_pending_handover: null,
        },
      ],
    });
    const user = userEvent.setup();
    renderWithIntl(<ReceivablesPage />);
    expect(await screen.findByText("Overdue (1 shop)")).toBeVisible();
    expect(screen.queryByText("Not due")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Days past due" }));
    expect(await screen.findAllByText("Not due")).not.toHaveLength(0);
    expect(calls.at(-1)!.url.searchParams.get("basis")).toBe("DUE_DATE");
  });
});

describe("A refund", () => {
  const refund = (status: "ISSUED" | "REVERSED") => ({
    id: "rf1",
    number: "RFD/26-27/000001",
    refund_date: "2026-09-28",
    retailer: shop,
    amount: "200.00",
    mode: "BANK_TRANSFER" as const,
    status,
    reference_no: "",
    notes: "",
    recorded_by_name: "Owner",
    voucher_pdf_status: "READY" as const,
    reversed_at: status === "REVERSED" ? "2026-09-28T12:00:00Z" : null,
    reversal_reason: status === "REVERSED" ? "Paid to the wrong shop" : "",
    paid_from: [],
  });

  it("is reversed with a reason by someone who records payments", async () => {
    permissions.add("payments.record");
    let current = refund("ISSUED");
    const calls = mockApi({
      "/api/v1/refunds/rf1/": () => [200, current],
      "POST /api/v1/refunds/rf1/reverse/": () => {
        current = refund("REVERSED");
        return [200, current];
      },
    });
    const user = userEvent.setup();
    renderWithIntl(<RefundDetailPage refundId="rf1" />);
    await user.click(await screen.findByRole("button", { name: "Reverse (error)" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/^Why/), "Paid to the wrong shop");
    await user.click(within(dialog).getByRole("button", { name: "Reverse (error)" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        reason: "Paid to the wrong shop",
      }),
    );
    expect(await screen.findByText(/The amount is back in the shop's credit/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Reverse (error)" })).toBeNull();
  });

  it("offers no reversal without payments.record", async () => {
    mockApi({ "/api/v1/refunds/rf1/": () => [200, refund("ISSUED")] });
    renderWithIntl(<RefundDetailPage refundId="rf1" />);
    expect(await screen.findByText("Paid back")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Reverse (error)" })).toBeNull();
  });
});

describe("Online payments for staff", () => {
  const onlinePayment: PaymentDetail = {
    ...payment,
    mode: "ONLINE",
    status: "RECEIVED",
    cheque_number: "",
    bank_name: "",
    handover_status: "NOT_TRACKED",
    collected_by_name: "",
    dated_in_previous_financial_year: false,
    held_as_credit_while_advances_off: null,
    gateway_payment_id: "pay_mock_1",
    needs_review: true,
    review_reason: "Paid ₹200.00; the checkout was for ₹210.00.",
    reviewed_at: null,
  };

  it("shows why an online payment needs a look, and marks it reviewed with a note", async () => {
    permissions.add("payments.record");
    const user = userEvent.setup();
    const calls = mockApi({
      "/api/v1/payments/p1/": () => [200, onlinePayment],
      "POST /api/v1/payments/p1/review/": () => [200, { ...onlinePayment, needs_review: false }],
    });
    renderWithIntl(<PaymentDetailPage paymentId="p1" />);
    expect(
      await screen.findByText(
        "This online payment needs a look: Paid ₹200.00; the checkout was for ₹210.00.",
      ),
    ).toBeVisible();
    expect(screen.getByText("pay_mock_1")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Mark reviewed" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/^Note/), "Rest paid in cash");
    await user.click(within(dialog).getByRole("button", { name: "Mark reviewed" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/payments/p1/review/")?.body).toEqual({
        note: "Rest paid in cash",
      }),
    );
  });

  it("filters online payments and those to review only while online payments are on", async () => {
    const row = { ...onlinePayment, needs_review: true };
    const calls = mockApi({
      "/api/v1/payments/": () => [200, { next: null, previous: null, results: [row] }],
    });
    const { unmount } = renderWithIntl(<PaymentsPage />);
    expect(await screen.findAllByText("RCT/26-27/000001")).not.toHaveLength(0);
    expect(screen.queryAllByLabelText("Needs review only")).toHaveLength(0);
    unmount();
    features.add("payments");
    renderWithIntl(<PaymentsPage />);
    expect((await screen.findAllByText("Needs review"))[0]).toBeVisible();
    await userEvent.setup().click(screen.getAllByLabelText("Needs review only")[0]!);
    await waitFor(() => expect(calls.at(-1)!.url.searchParams.get("needs_review")).toBe("true"));
  });
});
