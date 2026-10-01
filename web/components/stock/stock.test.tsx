import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Movement, StockDetail, StockRow } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";
import { setViewport } from "@/tests/viewport";

import { MovementsTable } from "./movements";
import { StockDetailPage } from "./stock-detail";
import { StockPage } from "./stock-page";

const permissions = new Set(["stock.view", "stock.inward", "stock.adjust", "costs.view"]);
// Stock planning and purchasing off: their card is tested in components/planning.
const auth = { me: { id: "u1" }, can: (p: string) => permissions.has(p), feature: () => false };
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const params = { value: new URLSearchParams() };
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/manage/stock",
  useSearchParams: () => params.value,
}));

afterEach(() => {
  vi.unstubAllGlobals();
  setViewport(1440);
  params.value = new URLSearchParams();
  for (const p of ["stock.inward", "stock.adjust", "costs.view"]) permissions.add(p);
});

const PCS = { code: "PCS", allows_decimal: false };
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
const page = (results: unknown[]) => ({ next: null, previous: null, results });
const summary = (awaiting: number | null = 2) => ({
  alerts: { LOW_STOCK: 3, OUT_OF_STOCK: 1, BACKORDER_DEMAND: 0 },
  receipts_awaiting_cost: awaiting,
});
const masters = {
  "/api/v1/categories/": () => [200, page([])] as [number, unknown],
  "/api/v1/brands/": () => [200, page([])] as [number, unknown],
};

describe("stock overview", () => {
  it("lists stock with its status and filters from the count cards", async () => {
    const calls = mockApi({
      ...masters,
      "/api/v1/stock/summary/": () => [200, summary()],
      "/api/v1/stock/": (_body, url) =>
        url.searchParams.get("status") === "LOW"
          ? [200, page([row("p2", "Marie", { status: "LOW", available: "4.000" })])]
          : [200, page([row("p1", "Parle-G"), row("p2", "Marie", { status: "LOW" })])],
    });
    renderWithIntl(<StockPage />);
    expect(await screen.findByText("Parle-G")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /2 goods receipts are waiting for costs/ }),
    ).toHaveAttribute("href", "/manage/stock/inwards?awaiting_cost=true");
    await userEvent.click(screen.getByRole("button", { name: /Low stock/ }));
    await waitFor(() => expect(screen.queryByText("Parle-G")).not.toBeInTheDocument());
    expect(calls.some((c) => c.url.searchParams.get("status") === "LOW")).toBe(true);
    expect(screen.getByRole("link", { name: "Receive goods" })).toHaveAttribute(
      "href",
      "/manage/stock/inwards/new",
    );
  });

  it("opens on products without a reorder level when linked from the report", async () => {
    params.value = new URLSearchParams("status=NO_REORDER_LEVEL");
    const calls = mockApi({
      ...masters,
      "/api/v1/stock/summary/": () => [200, summary(null)],
      "/api/v1/stock/": () => [200, page([row("p1", "Parle-G", { reorder_level: "0.000" })])],
    });
    renderWithIntl(<StockPage />);
    expect(await screen.findByText("Not set")).toBeInTheDocument();
    const listCall = calls.find((c) => c.path === "/api/v1/stock/");
    expect(listCall?.url.searchParams.get("no_reorder_level")).toBe("true");
    expect(screen.queryByText(/waiting for costs/)).not.toBeInTheDocument();
  });

  it("hides stock actions from staff who can only view stock", async () => {
    permissions.delete("stock.inward");
    permissions.delete("stock.adjust");
    mockApi({
      ...masters,
      "/api/v1/stock/summary/": () => [200, summary(null)],
      "/api/v1/stock/": () => [200, page([row("p1", "Parle-G")])],
    });
    renderWithIntl(<StockPage />);
    await screen.findByText("Parle-G");
    expect(screen.queryByRole("link", { name: "Receive goods" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Adjust stock" })).not.toBeInTheDocument();
  });

  it("shows cards on phones", async () => {
    setViewport(360);
    mockApi({
      ...masters,
      "/api/v1/stock/summary/": () => [200, summary()],
      "/api/v1/stock/": () => [200, page([row("p1", "Parle-G")])],
    });
    renderWithIntl(<StockPage />);
    expect(await screen.findByText("Parle-G")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

const movement = (extra: Partial<Movement> = {}): Movement => ({
  id: "m1",
  created_at: "2026-09-26T08:00:00Z",
  product: { id: "p1", code: "P1", name: "Parle-G", unit: PCS, pack_unit: null, pack_size: null },
  movement_type: "INWARD",
  quantity: "12.000",
  delta_on_hand: "12.000",
  delta_reserved: "0.000",
  on_hand_after: "52.000",
  reserved_after: "0.000",
  unit_cost: null,
  value: null,
  reference_type: "INWARD",
  reference_id: "r1",
  reference_number: "GRN-2026-00001",
  reason: "",
  by: "Warehouse (Sharma)",
  ...extra,
});

describe("movements", () => {
  it("links each movement to its document and shows value only when the server sends it", async () => {
    mockApi({
      "/api/v1/stock/movements/": () => [
        200,
        page([
          movement(),
          movement({
            id: "m2",
            movement_type: "DAMAGE",
            delta_on_hand: "-2.000",
            reference_type: "ADJUSTMENT",
            reference_id: "a1",
            reference_number: "ADJ-2026-00003",
            reason: "Wet cartons",
          }),
        ]),
      ],
    });
    renderWithIntl(<MovementsTable />);
    expect(await screen.findByRole("link", { name: "GRN-2026-00001" })).toHaveAttribute(
      "href",
      "/manage/stock/inwards/r1",
    );
    expect(screen.getByRole("link", { name: "ADJ-2026-00003" })).toHaveAttribute(
      "href",
      "/manage/stock/adjustments/a1",
    );
    const text = (value: string) => (_: string, el: Element | null) => el?.textContent === value;
    expect(screen.getAllByText(text("+12 PCS")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(text("−2 PCS")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("columnheader", { name: "Value" })).not.toBeInTheDocument();
  });
});

const detail = (extra: Partial<StockDetail> = {}): StockDetail => ({
  ...row("p1", "Parle-G"),
  barcodes: ["8901719101038"],
  cost_price: "8.50",
  open_alerts: [],
  recent_movements: [],
  ...extra,
});

describe("product stock page", () => {
  it("saves the reorder level and hides the cost without costs.view", async () => {
    permissions.delete("costs.view");
    const calls = mockApi({
      "/api/v1/stock/p1/": () => [200, detail({ cost_price: null })],
      "/api/v1/stock/movements/": () => [200, page([movement()])],
      "PATCH /api/v1/stock/p1/reorder-level/": () => [200, detail({ reorder_level: "24.000" })],
    });
    renderWithIntl(<StockDetailPage productId="p1" />);
    const field = await screen.findByLabelText("Reorder at (PCS)");
    expect(screen.queryByText("Cost price")).not.toBeInTheDocument();
    await userEvent.clear(field);
    await userEvent.type(field, "24");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ reorder_level: "24" }),
    );
    const section = screen.getByRole("region", { name: "Stock movements" });
    expect(within(section).getByText("GRN-2026-00001")).toBeInTheDocument();
  });

  it("shows the cost price to staff with costs.view", async () => {
    mockApi({
      "/api/v1/stock/p1/": () => [200, detail()],
      "/api/v1/stock/movements/": () => [200, page([])],
    });
    renderWithIntl(<StockDetailPage productId="p1" />);
    expect(await screen.findByText("Cost price")).toBeInTheDocument();
    expect(screen.getByText("₹8.50")).toBeInTheDocument();
  });
});
