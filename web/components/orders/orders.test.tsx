import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { OrderRow, StaffOrder, StaffOrderLine, WaitingLine } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { BackorderProductPage } from "./backorders";
import { OrdersBoard } from "./board";
import { StaffOrderPage } from "./order-detail";

const permissions = new Set<string>();
const features = new Set<string>();
const auth = {
  me: { id: "u1", tenant: { id: "t1" } },
  can: (p: string) => permissions.has(p),
  feature: (code: string) => features.has(code),
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/manage/orders",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  permissions.clear();
  features.clear();
});

const page = (results: unknown[]) => ({ next: null, previous: null, results });
const counts = { new: 2, on_hold: 1, backorders: 0, in_progress: 3, proposals: 0, to_pack: 1 };

const row = (id: string, extra: Partial<OrderRow> = {}): OrderRow => ({
  id,
  number: `ORD-2026-00000${id}`,
  status: "PLACED",
  items_to_follow: 0,
  backorder_state: "NONE",
  hold_reason: "",
  retailer: "r1",
  retailer_name: "Ganesh Kirana",
  placed_via: "RETAILER_APP",
  placed_by_label: "",
  placed_at: "2026-09-27T10:00:00Z",
  grand_total: "105.00",
  line_count: 1,
  ...extra,
});

function order(extra: Partial<StaffOrder> = {}): StaffOrder {
  return {
    id: "o1",
    number: "ORD-2026-000001",
    status: "PLACED",
    backorder_state: "NONE",
    hold_reason: "",
    retailer: "r1",
    retailer_name: "Ganesh Kirana",
    placed_via: "STAFF",
    placed_by_label: "Priya (Sales)",
    placed_at: "2026-09-27T10:00:00Z",
    accepted_at: null,
    closed_at: null,
    shipping_address: {},
    retailer_note: "",
    prices_include_tax: false,
    gross_total: "100.00",
    discount_total: "0.00",
    taxable_total: "100.00",
    tax_total: "5.00",
    round_off: "0.00",
    grand_total: "105.00",
    rejection_reason: "",
    cancellation_reason: "",
    items_to_follow: 1,
    lines: [],
    fulfilments: [],
    history: [],
    credit_approved_value: null,
    invoices: [],
    has_confirmation: false,
    ...extra,
  };
}

describe("Order board", () => {
  it("shows tabs with counts, partly delivered, and bulk accept only for orders.manage", async () => {
    permissions.add("orders.view");
    mockApi({
      "/api/v1/orders/counts/": () => [200, counts],
      "/api/v1/orders/": () => [
        200,
        page([row("1"), row("2", { status: "PARTLY_DELIVERED", items_to_follow: 2 })]),
      ],
    });
    const { unmount } = renderWithIntl(<OrdersBoard />);
    const newTab = await screen.findByRole("tab", { name: /New/ });
    await waitFor(() => expect(newTab).toHaveTextContent("2"));
    expect(screen.getByRole("tab", { name: /Completed/ })).not.toHaveTextContent(/\d/);
    expect(await screen.findAllByText("Partly delivered")).not.toHaveLength(0);
    expect(screen.getAllByText("2 items to follow")).not.toHaveLength(0);
    expect(screen.queryByRole("checkbox", { name: /Select order/ })).toBeNull();
    unmount();

    permissions.add("orders.manage");
    renderWithIntl(<OrdersBoard />);
    expect(
      await screen.findByRole("checkbox", { name: "Select order ORD-2026-000001" }),
    ).toBeVisible();
  });
});

describe("Order page", () => {
  it("shows the actions each role may take", async () => {
    mockApi({ "/api/v1/orders/o1/": () => [200, order()] });
    permissions.add("orders.view");
    permissions.add("orders.fulfil"); // warehouse
    const { unmount } = renderWithIntl(<StaffOrderPage orderId="o1" />);
    expect(await screen.findByRole("heading", { name: "ORD-2026-000001" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
    expect(screen.getByText(/Placed by Priya \(Sales\)/)).toBeVisible();
    unmount();

    permissions.add("orders.manage");
    renderWithIntl(<StaffOrderPage orderId="o1" />);
    expect(await screen.findByRole("button", { name: "Accept" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reject" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Change quantities" })).toBeVisible();
  });

  it("says when an order waits because of overdue bills, and lists the order's invoices", async () => {
    permissions.add("orders.view");
    permissions.add("invoices.view");
    mockApi({
      "/api/v1/orders/o1/": () => [
        200,
        order({
          status: "ON_HOLD",
          hold_reason: "OVERDUE",
          invoices: [
            {
              id: "i1",
              number: "INV/26-27/000001",
              invoice_date: "2026-09-27",
              grand_total: "105.00",
              balance_due: "105.00",
              payment_status: "UNPAID",
            },
          ],
          has_confirmation: true,
        }),
      ],
    });
    renderWithIntl(<StaffOrderPage orderId="o1" />);
    expect(await screen.findByText(/This shop has overdue bills/)).toBeVisible();
    expect(screen.getByRole("link", { name: "INV/26-27/000001" })).toHaveAttribute(
      "href",
      "/manage/invoices/i1",
    );
    expect(screen.getByRole("button", { name: /Order Confirmation/ })).toBeVisible();
  });

  it("accepts with an Idempotency-Key and approves a credit hold for credit.manage", async () => {
    permissions.add("orders.view");
    permissions.add("orders.manage");
    const calls = mockApi({
      "/api/v1/orders/o1/": () => [200, order()],
      "POST /api/v1/orders/o1/accept/": () => [200, order({ status: "ACCEPTED" })],
    });
    const user = userEvent.setup();
    const { unmount } = renderWithIntl(<StaffOrderPage orderId="o1" />);
    await user.click(await screen.findByRole("button", { name: "Accept" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/accept/"))).toBe(true));
    const accept = calls.find((c) => c.path.endsWith("/accept/"))!;
    expect(accept.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f]{32}$/);
    unmount();

    mockApi({ "/api/v1/orders/o1/": () => [200, order({ status: "ON_HOLD" })] });
    renderWithIntl(<StaffOrderPage orderId="o1" />);
    await screen.findByText(/over the shop's credit limit/);
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("shows what is on order for a waiting line, and when it's expected", async () => {
    permissions.add("orders.view");
    const line: StaffOrderLine = {
      id: "l1",
      line_no: 1,
      product: "p1",
      product_code: "TEA",
      product_name: "Tata Tea Gold",
      unit_code: "PCS",
      unit_price: "100.00",
      discount_per_unit: "0.00",
      gst_rate: "5.000",
      qty_ordered: "5.000",
      qty_pending: "0.000",
      qty_reserved: "2.000",
      qty_backordered: "3.000",
      qty_allocated: "0.000",
      qty_cancelled: "0.000",
      qty_dispatched: "0.000",
      qty_delivered: "0.000",
      ready_qty: "0.000",
      line_total: "525.00",
      on_order: { quantity: "12.000", expected_date: "2026-10-05", late: true },
      free_of_line: null,
      scheme_name: "",
    };
    mockApi({
      "/api/v1/orders/o1/": () => [
        200,
        order({ status: "ACCEPTED", backorder_state: "OPEN", lines: [line] }),
      ],
    });
    renderWithIntl(<StaffOrderPage orderId="o1" />);
    expect(await screen.findByText(/On order: 12 PCS/)).toHaveTextContent(
      "On order: 12 PCS expected 05-10-2026 · late",
    );
  });
});

const waiting = (extra: Partial<WaitingLine> = {}): WaitingLine => ({
  id: "l1",
  order: "o1",
  order_number: "ORD-2026-000001",
  placed_at: "2026-09-27T10:00:00Z",
  retailer: "r1",
  retailer_name: "Ganesh Kirana",
  product_code: "A",
  qty_ordered: "5.000",
  qty_backordered: "3.000",
  unit_price: "10.00",
  over_credit_limit: false,
  approved_over_limit: false,
  shop_blocked: false,
  ...extra,
});

describe("Backorder allocation", () => {
  it("flags lines and asks credit.manage users for a reason to allocate over the limit", async () => {
    permissions.add("orders.view");
    permissions.add("orders.allocate_backorder");
    permissions.add("credit.manage");
    const bodies: unknown[] = [];
    mockApi({
      "/api/v1/backorders/p1/": () => [
        200,
        [
          waiting(),
          waiting({ id: "l2", order_number: "ORD-2", approved_over_limit: true }),
          waiting({ id: "l3", order_number: "ORD-3", shop_blocked: true }),
        ],
      ],
      "/api/v1/backorders/": () => [200, []],
      "/api/v1/backorders/allocations/": () => [200, page([])],
      "POST /api/v1/backorders/allocate/": (body) => {
        bodies.push(body);
        return (body as { override_reason?: string }).override_reason
          ? [200, []]
          : [
              422,
              {
                error: {
                  code: "CREDIT_LIMIT_EXCEEDED",
                  message: "",
                  details: { retailer: "Ganesh Kirana", can_override: true },
                },
              },
            ];
      },
    });
    const user = userEvent.setup();
    renderWithIntl(<BackorderProductPage productId="p1" />);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Approved over limit")).toBeVisible();
    expect(within(table).getByText("Shop blocked")).toBeVisible();
    expect(screen.getByLabelText("Quantity to allocate to order ORD-3")).toBeDisabled();
    await user.type(screen.getByLabelText("Quantity to allocate to order ORD-2026-000001"), "2");
    await user.click(screen.getByRole("button", { name: "Allocate chosen" }));
    expect(await screen.findByText(/Ganesh Kirana is over its credit limit/)).toBeVisible();
    await user.type(screen.getByLabelText("Reason"), "Paid in cash");
    await user.click(screen.getByRole("button", { name: "Allocate anyway" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toEqual({
      product: "p1",
      allocations: [{ order_line: "l1", quantity: "2" }],
      override_reason: "Paid in cash",
    });
  });

  it("tells users without credit.manage who can allocate", async () => {
    permissions.add("orders.view");
    permissions.add("orders.allocate_backorder");
    mockApi({
      "/api/v1/backorders/p1/": () => [200, [waiting()]],
      "/api/v1/backorders/": () => [200, []],
      "/api/v1/backorders/allocations/": () => [200, page([])],
      "POST /api/v1/backorders/allocate/": () => [
        422,
        {
          error: {
            code: "CREDIT_LIMIT_EXCEEDED",
            message: "",
            details: { retailer: "Ganesh Kirana", can_override: false },
          },
        },
      ],
    });
    const user = userEvent.setup();
    renderWithIntl(<BackorderProductPage productId="p1" />);
    await user.type(
      await screen.findByLabelText("Quantity to allocate to order ORD-2026-000001"),
      "1",
    );
    await user.click(screen.getByRole("button", { name: "Allocate chosen" }));
    expect(await screen.findByText(/Someone who manages credit can allocate it/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Allocate anyway" })).toBeNull();
  });
});

describe("Backorders of a product", () => {
  it("shows what is on order from suppliers while purchasing is on", async () => {
    permissions.add("orders.view");
    features.add("purchasing");
    mockApi({
      "/api/v1/backorders/p1/": () => [200, [waiting()]],
      "/api/v1/backorders/": () => [
        200,
        [
          {
            product_id: "p1",
            product_code: "A",
            product_name: "Parle-G",
            unit_code: "PCS",
            waiting: "3.000",
            lines: 1,
            oldest_placed_at: "2026-09-27T10:00:00Z",
            available: "0.000",
            proposed: "0.000",
            skipped_credit: 0,
            blocked: 0,
            approved_over_limit: 0,
          },
        ],
      ],
      "/api/v1/backorders/allocations/": () => [200, page([])],
      "/api/v1/products/p1/on-order/": () => [
        200,
        { quantity: "24.000", expected_date: "2026-10-05", late: false },
      ],
    });
    renderWithIntl(<BackorderProductPage productId="p1" />);
    expect(await screen.findByText(/On order: 24 PCS/)).toHaveTextContent(
      "On order: 24 PCS, expected 05-10-2026",
    );
    expect(screen.queryByText("Late")).toBeNull();
  });
});
