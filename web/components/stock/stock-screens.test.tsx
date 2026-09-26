import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Alert, StockRow, ValuationRow } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { AdjustmentEditor, AdjustmentPage } from "./adjustments";
import { AlertsPage } from "./alerts";
import { LowStockReport, ReportsIndex, ValuationReport } from "./reports";

const permissions = new Set(["stock.view", "stock.adjust", "reports.stock", "costs.view"]);
const auth = { me: { id: "u1" }, can: (p: string) => permissions.has(p) };
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/manage/stock",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  router.replace.mockReset();
  permissions.add("costs.view");
});

const PCS = { code: "PCS", allows_decimal: false };
const page = (results: unknown[]) => ({ next: null, previous: null, results });
const row = (id: string, name: string, extra: Partial<StockRow> = {}): StockRow => ({
  id,
  code: id.toUpperCase(),
  name,
  unit: PCS,
  pack_unit: null,
  pack_size: null,
  category: "Biscuits",
  brand: "Parle",
  is_active: true,
  reorder_level: "10.000",
  on_hand: "40.000",
  reserved: "0.000",
  available: "40.000",
  backordered: "0.000",
  status: "IN_STOCK",
  thumbnail_url: null,
  ...extra,
});
const masters = {
  "/api/v1/categories/": () => [200, page([])] as [number, unknown],
  "/api/v1/brands/": () => [200, page([])] as [number, unknown],
};

describe("adjusting stock", () => {
  it("needs a reason, counts by default and posts every line with an idempotency key", async () => {
    const calls = mockApi({
      "/api/v1/stock/lookup/": () => [200, row("p1", "Parle-G")],
      "/api/v1/stock/": () => [200, page([])],
      "POST /api/v1/stock/adjustments/": () => [
        201,
        { id: "a1", number: "ADJ-2026-00004", unchanged: [], lines: [] },
      ],
    });
    renderWithIntl(<AdjustmentEditor />);
    await userEvent.type(screen.getByLabelText("Scan or search a product"), "8901719101038{Enter}");
    const counted = await screen.findByLabelText("Counted quantity of Parle-G in PCS");
    const save = screen.getByRole("button", { name: /Save adjustment/ });
    expect(save).toBeDisabled(); // no reason yet
    expect(screen.getByText(/now 40 PCS/)).toBeInTheDocument();
    await userEvent.type(counted, "37");
    await userEvent.click(screen.getByRole("radio", { name: "Stock count" }));
    await userEvent.type(screen.getByLabelText(/^Note/), "Monthly count");
    await userEvent.click(save);
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/manage/stock/adjustments/a1"),
    );
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      reason_code: "COUNT_CORRECTION",
      note: "Monthly count",
      lines: [{ product_id: "p1", mode: "COUNTED", quantity: "37" }],
    });
    expect(post?.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f]{32}$/);
  });

  it("can remove instead of count, and shows line errors from the server", async () => {
    mockApi({
      "/api/v1/stock/lookup/": () => [200, row("p1", "Parle-G")],
      "/api/v1/stock/": () => [200, page([])],
      "POST /api/v1/stock/adjustments/": () => [
        400,
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "Some fields need attention.",
            details: { fields: { "lines.1": ["Enter a quantity above 0."] } },
          },
        },
      ],
    });
    renderWithIntl(<AdjustmentEditor />);
    await userEvent.type(screen.getByLabelText("Scan or search a product"), "8901719101038{Enter}");
    await userEvent.click(await screen.findByRole("radio", { name: "Remove" }));
    expect(screen.getByLabelText("Quantity of Parle-G to remove, in PCS")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Damaged" }));
    await userEvent.type(screen.getByLabelText(/^Note/), "Wet");
    await userEvent.click(screen.getByRole("button", { name: /Save adjustment/ }));
    expect(await screen.findByText("Enter a quantity above 0.")).toBeInTheDocument();
  });

  it("shows a saved adjustment with each change", async () => {
    mockApi({
      "/api/v1/stock/adjustments/a1/": () => [
        200,
        {
          id: "a1",
          number: "ADJ-2026-00004",
          reason_code: "DAMAGE",
          note: "Wet cartons",
          line_count: 1,
          created_at: "2026-09-26T08:00:00Z",
          created_by: "Warehouse",
          unchanged: [],
          lines: [
            {
              id: "l1",
              line_no: 1,
              product: {
                id: "p1",
                code: "P1",
                name: "Parle-G",
                unit: PCS,
                pack_unit: null,
                pack_size: null,
              },
              mode: "REMOVE",
              entered_qty: "2.000",
              quantity_change: "-2.000",
              on_hand_before: "40.000",
            },
          ],
        },
      ],
    });
    renderWithIntl(<AdjustmentPage adjustmentId="a1" />);
    expect(await screen.findByRole("heading", { name: "ADJ-2026-00004" })).toBeInTheDocument();
    expect(screen.getByText("Damaged · Warehouse")).toBeInTheDocument();
    expect(screen.getByText("Wet cartons")).toBeInTheDocument();
  });
});

const alert = (extra: Partial<Alert> = {}): Alert => ({
  id: "al1",
  product: { id: "p1", code: "P1", name: "Parle-G", unit: PCS, pack_unit: null, pack_size: null },
  alert_type: "LOW_STOCK",
  status: "OPEN",
  opened_at: "2026-09-26T08:00:00Z",
  resolved_at: null,
  value_at_open: "4.000",
  ...extra,
});

describe("alerts", () => {
  it("lists open alerts and switches to resolved ones", async () => {
    const calls = mockApi({
      "/api/v1/stock/alerts/": (_b, url) =>
        url.searchParams.get("status") === "RESOLVED"
          ? [
              200,
              page([alert({ id: "al2", status: "RESOLVED", resolved_at: "2026-09-26T09:00:00Z" })]),
            ]
          : [200, page([alert()])],
    });
    renderWithIntl(<AlertsPage />);
    expect(await screen.findByText("Low stock")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Resolved" }));
    expect(await screen.findByRole("columnheader", { name: "Resolved" })).toBeInTheDocument();
    expect(calls.at(-1)?.url.searchParams.get("status")).toBe("RESOLVED");
  });
});

describe("reports", () => {
  it("low stock prompts to set missing reorder levels", async () => {
    mockApi({
      ...masters,
      "/api/v1/reports/stock/low-stock/summary/": () => [
        200,
        { low_stock: 1, without_reorder_level: 7 },
      ],
      "/api/v1/reports/stock/low-stock/": () => [
        200,
        page([{ ...row("p2", "Marie", { available: "3.000" }), shortfall: "7.000" }]),
      ],
    });
    renderWithIntl(<LowStockReport />);
    expect(await screen.findByText("Marie")).toBeInTheDocument();
    expect(
      await screen.findByRole("link", { name: /7 active products have no reorder level/ }),
    ).toHaveAttribute("href", "/manage/stock?status=NO_REORDER_LEVEL");
  });

  it("valuation marks products without a cost and filters to them", async () => {
    const valued = (id: string, cost: string | null): ValuationRow => ({
      ...row(id, id === "p1" ? "Parle-G" : "Marie"),
      cost_price: cost,
      value: cost ? "340.00" : null,
    });
    const calls = mockApi({
      ...masters,
      "/api/v1/reports/stock/valuation/": () => [
        200,
        {
          total_value: "340.00",
          products_valued: 1,
          missing_cost: 1,
          by_category: [{ name: "Biscuits", value: "340.00", products: 2, missing_cost: 1 }],
          by_brand: [{ name: "", value: "340.00", products: 2, missing_cost: 1 }],
        },
      ],
      "/api/v1/reports/stock/valuation/products/": (_b, url) =>
        url.searchParams.get("missing_cost") === "true"
          ? [200, page([valued("p2", null)])]
          : [200, page([valued("p1", "8.50"), valued("p2", null)])],
    });
    renderWithIntl(<ValuationReport />);
    expect(await screen.findByText("Parle-G")).toBeInTheDocument();
    expect(screen.getAllByText("₹340.00").length).toBeGreaterThan(0);
    expect(screen.getByText("No cost price", { selector: "span" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Without a cost price/ }));
    await waitFor(() => expect(screen.queryByText("Parle-G")).not.toBeInTheDocument());
    expect(calls.some((c) => c.url.searchParams.get("missing_cost") === "true")).toBe(true);
    await userEvent.click(screen.getByRole("tab", { name: "Brand" }));
    expect(screen.getByText("(none)")).toBeInTheDocument();
  });

  it("offers the valuation report only with costs.view", () => {
    permissions.delete("costs.view");
    renderWithIntl(<ReportsIndex />);
    expect(screen.getByRole("link", { name: /Low stock/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Stock value/ })).not.toBeInTheDocument();
  });
});
