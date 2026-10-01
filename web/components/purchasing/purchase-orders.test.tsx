import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  PurchaseOrderDetail,
  PurchaseOrderLine,
  PurchaseOrderList,
} from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { EditPurchaseOrderPage, PurchaseOrderPage, PurchaseOrdersPage } from "./purchase-orders";

let permissions = new Set<string>();
const auth = {
  me: { id: "u1" },
  can: (p: string) => permissions.has(p),
  feature: (code: string) => code === "purchasing",
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/manage/purchasing/orders",
  useSearchParams: () => new URLSearchParams(),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), message: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

beforeEach(() => {
  permissions = new Set(["purchasing.view", "purchasing.manage", "costs.view", "stock.inward"]);
  router.replace.mockReset();
  router.push.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

const page = (results: unknown[]) =>
  [200, { next: null, previous: null, results }] as [number, unknown];

const listRow = (extra: Partial<PurchaseOrderList> = {}): PurchaseOrderList => ({
  id: "po1",
  number: "PO-2026-00003",
  status: "PARTLY_RECEIVED",
  supplier_id: "s1",
  supplier_name: "Hindustan Traders",
  expected_date: "2026-09-28",
  is_late: true,
  line_count: 3,
  subtotal: "875.00",
  revision: 1,
  changed_since_sent: false,
  sent_at: "2026-09-21T05:00:00Z",
  created_at: "2026-09-21T05:00:00Z",
  ...extra,
});

const poLine = (extra: Partial<PurchaseOrderLine> = {}): PurchaseOrderLine => ({
  id: "l1",
  line_no: 1,
  product_id: "p1",
  product_code: "TEA",
  product_name: "Tata Tea Gold",
  supplier_code: "HT-77",
  unit_code: "PCS",
  pack_unit_code: null,
  pack_size: null,
  entered_unit: "BASE",
  entered_qty: "10.000",
  quantity: "10.000",
  entered_cost: "75.5000",
  unit_cost: "75.5000",
  gst_rate: "5.000",
  line_total: "755.00",
  qty_received: "4.000",
  qty_cancelled: "0.000",
  due: "6.000",
  ...extra,
});

const order = (extra: Partial<PurchaseOrderDetail> = {}): PurchaseOrderDetail => ({
  ...listRow({ status: "SENT", is_late: false }),
  notes: "Please deliver before noon.",
  estimated_tax: "43.75",
  supplier_snapshot: {},
  send_to_email: "orders@hindustan.example.com",
  sent_by: "Owner",
  closed_at: null,
  closed_reason: "",
  pdf_status: "READY",
  lines: [poLine({ qty_received: "0.000", due: "10.000" })],
  receipts: [],
  actions: ["edit", "send", "receive", "cancel"],
  ...extra,
});

describe("PurchaseOrdersPage", () => {
  it("lists orders with their status, lateness and value, and filters late ones", async () => {
    const calls = mockApi({
      "/api/v1/suppliers/": () => page([{ id: "s1", name: "Hindustan Traders" }]),
      "/api/v1/purchase-orders/": () => page([listRow()]),
    });
    renderWithIntl(<PurchaseOrdersPage />);
    const row = (await screen.findByText("PO-2026-00003")).closest("tr")!;
    expect(within(row).getByText("Partly received")).toBeInTheDocument();
    expect(within(row).getByText("Late")).toBeInTheDocument();
    expect(within(row).getByText("₹875.00")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "Arrival" }));
    await userEvent.click(await screen.findByRole("option", { name: "Late only" }));
    await waitFor(() => expect(calls.at(-1)?.url.searchParams.get("late")).toBe("true"));
  });

  it("shows no value to staff who can't see costs", async () => {
    permissions.delete("costs.view");
    mockApi({
      "/api/v1/suppliers/": () => page([]),
      "/api/v1/purchase-orders/": () => page([listRow({ subtotal: null })]),
    });
    renderWithIntl(<PurchaseOrdersPage />);
    await screen.findByText("PO-2026-00003");
    expect(screen.queryByRole("columnheader", { name: "Value (before GST)" })).toBeNull();
  });
});

describe("PurchaseOrderPage", () => {
  it("sends the order and offers its link for WhatsApp", async () => {
    const calls = mockApi({
      "/api/v1/purchase-orders/po1/": () => [200, order()],
      "POST /api/v1/purchase-orders/po1/send/": () => [
        200,
        {
          order: order({ revision: 1 }),
          share_link: "https://sharma.example.com/api/v1/public/documents/tok/",
          emailed: true,
        },
      ],
    });
    renderWithIntl(<PurchaseOrderPage orderId="po1" />);
    const line = (await screen.findByText("Tata Tea Gold")).closest("tr")!;
    expect(within(line).getByText("₹755.00")).toBeInTheDocument();
    expect(screen.getByText("₹43.75")).toBeInTheDocument(); // the GST estimate
    await userEvent.click(screen.getByRole("button", { name: "Send again" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(
      within(confirm).getByText(/emailed to orders@hindustan.example.com/),
    ).toBeInTheDocument();
    await userEvent.click(within(confirm).getByRole("button", { name: "Send to supplier" }));
    const share = await screen.findByRole("link", { name: "Share on WhatsApp" });
    expect(share.getAttribute("href")).toBe(
      `https://wa.me/?text=${encodeURIComponent(
        "Purchase order PO-2026-00003: https://sharma.example.com/api/v1/public/documents/tok/",
      )}`,
    );
    const send = calls.find((c) => c.path === "/api/v1/purchase-orders/po1/send/")!;
    expect(send.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f]{32}$/);
  });

  it("cancels a sent order, emailing the supplier unless told not to", async () => {
    const calls = mockApi({
      "/api/v1/purchase-orders/po1/": () => [200, order()],
      "POST /api/v1/purchase-orders/po1/cancel/": () => [200, order({ status: "CANCELLED" })],
    });
    renderWithIntl(<PurchaseOrderPage orderId="po1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel order" }));
    const dialog = await screen.findByRole("dialog");
    const go = within(dialog).getByRole("button", { name: "Cancel order" });
    expect(go).toBeDisabled(); // a sent order needs a reason
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Ordered elsewhere");
    const email = within(dialog).getByRole("checkbox", { name: /Email the supplier/ });
    expect(email).toBeChecked();
    await userEvent.click(email);
    await userEvent.click(go);
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        reason: "Ordered elsewhere",
        notify_supplier: false,
      }),
    );
  });

  it("receives goods into a goods-receipt draft", async () => {
    mockApi({
      "/api/v1/purchase-orders/po1/": () => [200, order()],
      "POST /api/v1/purchase-orders/po1/receive/": () => [201, { id: "r9" }],
    });
    renderWithIntl(<PurchaseOrderPage orderId="po1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Receive goods" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/manage/stock/inwards/r9"));
  });

  it("offers only what the order allows and hides prices without costs.view", async () => {
    permissions = new Set(["purchasing.view", "stock.inward"]);
    mockApi({
      "/api/v1/purchase-orders/po1/": () => [
        200,
        order({
          status: "PARTLY_RECEIVED",
          actions: ["receive", "close"],
          subtotal: null,
          estimated_tax: null,
          lines: [poLine({ unit_cost: null, entered_cost: null, line_total: null })],
          receipts: [
            {
              id: "r1",
              number: "GRN-2026-00007",
              status: "POSTED",
              posted_at: "2026-09-25T05:00:00Z",
            },
          ],
        }),
      ],
    });
    renderWithIntl(<PurchaseOrderPage orderId="po1" />);
    expect(await screen.findByRole("button", { name: "Receive goods" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close the rest" })).toBeNull(); // needs manage
    expect(screen.queryByRole("link", { name: "Edit" })).toBeNull();
    expect(screen.getByRole("button", { name: "PDF (without prices)" })).toBeInTheDocument();
    expect(screen.queryByText("Value before GST")).toBeNull();
    expect(screen.getByRole("link", { name: "GRN-2026-00007" })).toHaveAttribute(
      "href",
      "/manage/stock/inwards/r1",
    );
  });
});

describe("EditPurchaseOrderPage", () => {
  it("changes a line and saves the whole order", async () => {
    const calls = mockApi({
      "/api/v1/purchase-orders/po1/": () => [200, order()],
      "/api/v1/suppliers/": () => page([{ id: "s1", name: "Hindustan Traders" }]),
      "/api/v1/stock/": () => page([]),
      "PATCH /api/v1/purchase-orders/po1/": () => [200, order({ changed_since_sent: true })],
    });
    renderWithIntl(<EditPurchaseOrderPage orderId="po1" />);
    expect(
      await screen.findByText(/send it again so the supplier gets the revised copy/),
    ).toBeInTheDocument();
    const qty = screen.getByLabelText("Quantity of Tata Tea Gold in PCS");
    await userEvent.clear(qty);
    await userEvent.type(qty, "12");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/manage/purchasing/orders/po1"),
    );
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
      supplier_id: "s1",
      expected_date: "2026-09-28",
      notes: "Please deliver before noon.",
      lines: [
        {
          id: "l1",
          product_id: "p1",
          entered_unit: "BASE",
          entered_qty: "12",
          entered_cost: "75.5",
        },
      ],
    });
  });
});
