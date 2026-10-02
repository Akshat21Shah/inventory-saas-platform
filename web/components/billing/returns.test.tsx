import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReturnRequest, ShopInvoiceDetail } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";
import { setViewport } from "@/tests/viewport";

import { ShopBillPage } from "../shop/account";
import { ReturnRequestPage, ReturnRequestsPage } from "./returns";

const permissions = new Set<string>(["invoices.view", "invoices.manage"]);
vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({
    me: { id: "u1", tenant: { id: "t1" }, retailer: { on_hold: false } },
    can: (p: string) => permissions.has(p),
    feature: () => false,
  }),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/manage/invoices/returns",
  useSearchParams: () => new URLSearchParams(),
}));
afterEach(() => vi.unstubAllGlobals());

const request = (extra: Partial<ReturnRequest> = {}): ReturnRequest => ({
  id: "rr1",
  number: "RR-2026-000001",
  status: "REQUESTED",
  reason: "DAMAGED",
  note: "Packets torn",
  created_at: "2026-10-01T10:00:00Z",
  decided_at: null,
  decision_note: "",
  retailer: { id: "r1", code: "R-00001", shop_name: "Ganesh Kirana" },
  invoice: { id: "i1", number: "INV/26-27/000001" },
  credit_note: null,
  lines: [
    {
      id: "rl1",
      invoice_line_id: "l1",
      description: "Assam tea 250 g",
      product_code: "A",
      unit_code: "PCS",
      is_free: false,
      invoiced_quantity: "10.000",
      quantity: "4.000",
      approved_quantity: null,
      disposition: "",
    },
  ],
  ...extra,
});
const page = (results: unknown[]) =>
  [200, { next: null, previous: null, results }] as [number, unknown];

describe("Return requests for staff", () => {
  it("lists the requests waiting first", async () => {
    const calls = mockApi({ "/api/v1/return-requests/": () => page([request()]) });
    renderWithIntl(<ReturnRequestsPage />);
    const row = (await screen.findByText("RR-2026-000001")).closest("tr")!;
    expect(within(row).getByText("4 Assam tea 250 g")).toBeInTheDocument();
    expect(within(row).getByText("Waiting for you")).toBeInTheDocument();
    expect(calls[0]!.url.search).toContain("status=REQUESTED");
  });

  it("shows cards on a phone", async () => {
    setViewport(360);
    mockApi({ "/api/v1/return-requests/": () => page([request()]) });
    renderWithIntl(<ReturnRequestsPage />);
    await screen.findByText("RR-2026-000001");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("approves what came back and what happened to it", async () => {
    const calls = mockApi({
      "/api/v1/return-requests/rr1/": () => [200, request()],
      "POST /api/v1/return-requests/rr1/approve/": () => [
        200,
        request({ status: "APPROVED", credit_note: { id: "cn1", number: "CN/26-27/000004" } }),
      ],
    });
    renderWithIntl(<ReturnRequestPage requestId="rr1" />);
    const qty = await screen.findByLabelText("Quantity to credit for Assam tea 250 g");
    await userEvent.clear(qty);
    await userEvent.type(qty, "3");
    await userEvent.click(
      screen.getByRole("combobox", { name: "What happened to Assam tea 250 g" }),
    );
    await userEvent.click(await screen.findByRole("option", { name: "Received damaged" }));
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        lines: [{ line: "rl1", quantity: "3", disposition: "DAMAGED" }],
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("Approved. The credit note is issued.");
  });

  it("shows the outcome once decided", async () => {
    mockApi({
      "/api/v1/return-requests/rr1/": () => [
        200,
        request({ status: "REJECTED", decision_note: "Sold 40 days ago" }),
      ],
    });
    renderWithIntl(<ReturnRequestPage requestId="rr1" />);
    expect(await screen.findByText("Sold 40 days ago")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });
});

describe("Returns in the shop app", () => {
  const bill = (extra: Partial<ShopInvoiceDetail> = {}): ShopInvoiceDetail =>
    ({
      id: "i1",
      number: "INV/26-27/000001",
      invoice_date: "2026-10-01",
      due_date: "2026-10-31",
      order: { id: "o1", number: "ORD-2026-000001" },
      balance_due: "1296.00",
      grand_total: "1296.00",
      amount_paid: "0.00",
      amount_credited: "0.00",
      days_overdue: 0,
      status: "ISSUED",
      payment_status: "UNPAID",
      lines: [
        {
          id: "l1",
          line_no: 1,
          description: "Assam tea 250 g",
          unit_code: "PCS",
          quantity: "10.000",
          unit_price: "123.45",
          line_total: "1296.22",
          credited_quantity: "0.000",
          is_free: false,
          scheme_name: "",
        },
      ],
      credit_notes: [],
      return_requests: [],
      can_request_return: true,
      returnable: [{ invoice_line_id: "l1", quantity: "10.000" }],
      ...extra,
    }) as unknown as ShopInvoiceDetail;

  it("asks to return items from a bill", async () => {
    const calls = mockApi({
      "/api/v1/shop/invoices/i1/": () => [200, bill()],
      "POST /api/v1/shop/return-requests/": () => [201, request()],
    });
    renderWithIntl(<ShopBillPage invoiceId="i1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Return items" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Assam tea 250 g/), "2");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        invoice: "i1",
        reason: "DAMAGED",
        note: "",
        lines: [{ invoice_line: "l1", quantity: "2" }],
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("Sent. Your distributor will check it.");
  });

  it("follows a request and withdraws it while it waits", async () => {
    const calls = mockApi({
      "/api/v1/shop/invoices/i1/": () => [
        200,
        bill({ return_requests: [request()], can_request_return: false }),
      ],
      "POST /api/v1/shop/return-requests/rr1/cancel/": () => [
        200,
        request({ status: "CANCELLED" }),
      ],
    });
    renderWithIntl(<ShopBillPage invoiceId="i1" />);
    expect(await screen.findByText("Waiting for your distributor")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Return items" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Withdraw" }));
    await userEvent.click(await screen.findByRole("button", { name: "Withdraw" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  });
});
