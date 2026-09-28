import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Dues, PaymentDetail, ReceivablesPage as Page } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { HandoverPage, NewPaymentPage, PaymentDetailPage } from "./payments";
import { ReceivablesPage } from "./receivables";

const permissions = new Set<string>();
const auth = { me: { id: "u1", tenant: { id: "t1" } }, can: (p: string) => permissions.has(p) };
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
