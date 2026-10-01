import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ProductStats, ReorderSuggestion } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";
import { setViewport } from "@/tests/viewport";

import { ProductPlanningCard } from "./product-planning";
import { SuggestionsPage } from "./suggestions";

let permissions = new Set<string>();
let features = new Set<string>();
const auth = {
  me: { id: "u1" },
  can: (p: string) => permissions.has(p),
  feature: (code: string) => features.has(code),
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/manage/stock/reorder",
  useSearchParams: () => new URLSearchParams(),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), message: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

beforeEach(() => {
  permissions = new Set(["purchasing.view", "purchasing.manage", "stock.view", "stock.adjust"]);
  features = new Set(["stock_planning", "purchasing"]);
  toast.success.mockReset();
  toast.error.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
  setViewport(1440);
});

const page = (results: unknown[]) =>
  [200, { next: null, previous: null, results }] as [number, unknown];

const suggestion = (extra: Partial<ReorderSuggestion> = {}): ReorderSuggestion => ({
  id: "g1",
  status: "OPEN",
  product_id: "p1",
  product_code: "TEA",
  product_name: "Tata Tea Gold",
  unit_code: "PCS",
  supplier_id: "s1",
  supplier_name: "Hindustan Traders",
  basis: "DEMAND",
  computed_at: "2026-10-01T00:30:00Z",
  demand_qty: "60.000",
  demand_days: 30,
  per_day: "2.000",
  demand_rate: { quantity: "2.00", period: "DAY" },
  available: "4.000",
  on_order: "12.000",
  waiting: "3.000",
  reorder_level: "10.000",
  lead_days: 5,
  lead_source: "PRODUCT_SUPPLIER",
  safety_days: 7,
  cover_days: 14,
  reorder_point: "24.000",
  pack_size: "12.000",
  suggested_qty: "48.000",
  quantity: null,
  to_order: "48.000",
  packs: 4,
  days_left: "2.0",
  last_sale_date: "2026-09-30",
  ...extra,
});

describe("SuggestionsPage", () => {
  it("explains each suggestion in plain words, with its supplier and days left", async () => {
    mockApi({
      "/api/v1/suppliers/": () => page([{ id: "s1", name: "Hindustan Traders" }]),
      "/api/v1/reorder-suggestions/": () =>
        page([
          suggestion(),
          suggestion({
            id: "g2",
            product_id: "p2",
            product_name: "Parle-G",
            supplier_id: null,
            supplier_name: null,
            basis: "LOW_HISTORY",
            waiting: "0.000",
            on_order: "0.000",
            pack_size: null,
            packs: null,
            days_left: null,
            last_sale_date: null,
          }),
          suggestion({
            id: "g3",
            product_id: "p3",
            product_name: "Old Oats",
            basis: "LOW_HISTORY",
            available: "0.000",
            on_order: "0.000",
            reorder_level: "0.000",
            pack_size: null,
            packs: null,
            to_order: "3.000",
            days_left: null,
          }),
        ]),
    });
    renderWithIntl(<SuggestionsPage />);
    const tea = (await screen.findByText("Tata Tea Gold")).closest("tr")!;
    // The action and its urgency first, then why.
    expect(
      within(tea).getByText(
        "Order 48 PCS (4 packs of 12) · about 2 days of stock left, 3 PCS waiting",
      ),
    ).toBeInTheDocument();
    expect(
      within(tea).getByText(
        "Shops ordered 60 PCS in the last 30 days (about 2 PCS a day). 4 PCS available, 3 waiting for " +
          "shops, 12 on order. Reorder at 24 PCS: 5 days to arrive (the supplier's time for " +
          "this product) plus 7 days of safety stock. This order covers 14 days after it " +
          "arrives and the 3 PCS shops are waiting for. Rounded up to packs of 12 PCS.",
      ),
    ).toBeInTheDocument();
    expect(within(tea).getByText("About 2 days")).toBeInTheDocument();
    expect(within(tea).getByText("Hindustan Traders")).toBeInTheDocument();
    expect(within(tea).getByLabelText("Quantity of Tata Tea Gold to order, in PCS")).toHaveValue(
      "48",
    );

    const biscuits = screen.getByText("Parle-G").closest("tr")!;
    expect(
      within(biscuits).getByText(
        "Little sales history, so this goes by the reorder level and any shops waiting. " +
          "4 PCS available. It brings stock up to the reorder level of 10 PCS.",
      ),
    ).toBeInTheDocument();
    expect(within(biscuits).getByText("Order 48 PCS · at its reorder level")).toBeInTheDocument();
    expect(within(biscuits).getByText("At reorder level")).toBeInTheDocument();
    expect(within(biscuits).getByText("No preferred supplier")).toBeInTheDocument();

    // Sold before, but no order lately; out of stock, shops waiting, no reorder level.
    const oats = screen.getByText("Old Oats").closest("tr")!;
    expect(within(oats).getByText("Order 3 PCS · out of stock, 3 PCS waiting")).toBeInTheDocument();
    expect(
      within(oats).getByText(
        "No shop ordered this in the last 30 days, so this goes by the reorder level and any " +
          "shops waiting. 0 PCS available, 3 waiting for shops. It covers the 3 PCS shops are " +
          "waiting for.",
      ),
    ).toBeInTheDocument();
    expect(within(oats).getByText("Out of stock")).toBeInTheDocument();
  });

  it("shows the days left in whole days, and less than a day", async () => {
    mockApi({
      "/api/v1/suppliers/": () => page([]),
      "/api/v1/reorder-suggestions/": () =>
        page([
          suggestion({ days_left: "12.0", waiting: "0.000" }),
          suggestion({ id: "g2", product_name: "Quick Tea", days_left: "0.0", waiting: "0.000" }),
        ]),
    });
    renderWithIntl(<SuggestionsPage />);
    expect(
      await screen.findByText("Order 48 PCS (4 packs of 12) · about 12 days of stock left"),
    ).toBeInTheDocument();
    expect(screen.getByText("About 12 days")).toBeInTheDocument();
    expect(
      screen.getByText("Order 48 PCS (4 packs of 12) · less than a day of stock left"),
    ).toBeInTheDocument();
    expect(screen.getByText("Less than a day")).toBeInTheDocument();
  });

  it("lists products below their reorder level that aren't selling, apart", async () => {
    const calls = mockApi({
      "/api/v1/suppliers/": () => page([]),
      "/api/v1/reorder-suggestions/": (_body, url) =>
        url.searchParams.get("status") === "NOT_SELLING"
          ? page([
              suggestion({
                id: "g9",
                status: "NOT_SELLING",
                product_id: "p9",
                product_name: "Dusty Dates",
                basis: "LOW_HISTORY",
                available: "17.000",
                reorder_level: "24.000",
              }),
            ])
          : page([]),
    });
    const user = userEvent.setup();
    renderWithIntl(<SuggestionsPage />);
    expect(await screen.findByText("Nothing to reorder")).toBeInTheDocument();
    await user.click(screen.getByRole("combobox", { name: "Show" }));
    await user.click(
      await screen.findByRole("option", { name: "Below reorder level, not selling" }),
    );
    const row = (await screen.findByText("Dusty Dates")).closest("tr")!;
    expect(calls.at(-1)?.url.searchParams.get("status")).toBe("NOT_SELLING");
    expect(
      within(row).getByText(
        "Below its reorder level but not selling. Consider lowering the reorder level.",
      ),
    ).toBeInTheDocument();
    expect(within(row).getByText("17 PCS available · reorder level 24 PCS")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Change the reorder level" })).toHaveAttribute(
      "href",
      "/manage/stock/p9",
    );
    expect(within(row).queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull(); // never ordered from here
  });

  it("folds the explanation away on phones", async () => {
    setViewport(360);
    mockApi({
      "/api/v1/suppliers/": () => page([]),
      "/api/v1/reorder-suggestions/": () => page([suggestion()]),
    });
    const user = userEvent.setup();
    renderWithIntl(<SuggestionsPage />);
    expect(
      await screen.findByText(
        "Order 48 PCS (4 packs of 12) · about 2 days of stock left, 3 PCS waiting",
      ),
    ).toBeVisible();
    const explanation = screen.getByText(/^Shops ordered 60 PCS/);
    expect(explanation).not.toBeVisible();
    await user.click(screen.getByText("Why this much"));
    expect(explanation).toBeVisible();
  });

  it("tells slow demand per week or month, and less than 1 a month", async () => {
    mockApi({
      "/api/v1/suppliers/": () => page([]),
      "/api/v1/reorder-suggestions/": () =>
        page([
          suggestion({
            demand_qty: "2.000",
            per_day: "0.067",
            demand_rate: { quantity: "2.00", period: "MONTH" },
          }),
          suggestion({
            id: "g2",
            product_name: "Loose Rice",
            unit_code: "KG",
            demand_qty: "10.000",
            per_day: "0.333",
            demand_rate: { quantity: "2.33", period: "WEEK" },
            available: "1.500",
            reorder_point: "4.670",
          }),
          suggestion({
            id: "g3",
            product_name: "Rare Spice",
            demand_qty: "1.000",
            demand_days: 180,
            demand_rate: { quantity: "0.00", period: "MONTH" },
          }),
        ]),
    });
    renderWithIntl(<SuggestionsPage />);
    expect(
      await screen.findByText(/^Shops ordered 2 PCS in the last 30 days \(about 2 PCS a month\)\./),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /^Shops ordered 10 KG in the last 30 days \(about 2.33 KG a week\)\. 1.5 KG available.*Reorder at 4.67 KG/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/in the last 180 days \(less than 1 PCS a month\)/),
    ).toBeInTheDocument();
  });

  it("changes the quantity to order and dismisses a suggestion", async () => {
    const calls = mockApi({
      "/api/v1/suppliers/": () => page([]),
      "/api/v1/reorder-suggestions/": () => page([suggestion()]),
      "PATCH /api/v1/reorder-suggestions/g1/": () => [200, suggestion()],
    });
    const user = userEvent.setup();
    renderWithIntl(<SuggestionsPage />);
    const quantity = await screen.findByLabelText("Quantity of Tata Tea Gold to order, in PCS");
    await user.clear(quantity);
    await user.type(quantity, "60{Enter}");
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ quantity: "60" }),
    );

    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Dismiss the suggestion for Tata Tea Gold?",
    });
    await user.type(within(dialog).getByLabelText("Until"), "2026-10-15");
    await user.click(within(dialog).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Suggestion dismissed"));
    expect(calls.filter((c) => c.method === "PATCH").at(-1)?.body).toEqual({
      dismiss: true,
      until: "2026-10-15",
    });
  });

  it("creates draft purchase orders for the chosen suggestions, once", async () => {
    const calls = mockApi({
      "/api/v1/suppliers/": () => page([]),
      "/api/v1/reorder-suggestions/": () => page([suggestion()]),
      "POST /api/v1/reorder-suggestions/create-orders/": () => [
        201,
        [{ id: "po1", number: "PO-2026-00007", supplier_name: "Hindustan Traders", line_count: 1 }],
      ],
      "POST /api/v1/reorder-suggestions/apply-reorder-levels/": () => [200, { changed: 1 }],
    });
    const user = userEvent.setup();
    renderWithIntl(<SuggestionsPage />);
    await user.click(await screen.findByRole("checkbox", { name: "Select Tata Tea Gold" }));
    await user.click(screen.getByRole("button", { name: "Create purchase orders" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Draft purchase order PO-2026-00007 created"),
    );
    const created = calls.find((c) => c.path.endsWith("/create-orders/"))!;
    expect(created.body).toEqual({ suggestion_ids: ["g1"] });
    expect(created.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f]{32}$/);

    await user.click(await screen.findByRole("checkbox", { name: "Select Tata Tea Gold" }));
    await user.click(screen.getByRole("button", { name: "Use as reorder levels" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Reorder level set for 1 product"),
    );
    expect(calls.find((c) => c.path.endsWith("/apply-reorder-levels/"))?.body).toEqual({
      suggestion_ids: ["g1"],
    });
  });

  it("works the figures out again on request, and says when it's too soon", async () => {
    mockApi({
      "/api/v1/suppliers/": () => page([]),
      "/api/v1/reorder-suggestions/": () => page([]),
      "POST /api/v1/planning/stats/refresh/": () => [
        429,
        { error: { code: "RATE_LIMITED", message: "", details: {} } },
      ],
    });
    const user = userEvent.setup();
    renderWithIntl(<SuggestionsPage />);
    expect(await screen.findByText("Nothing to reorder")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Work out again now" }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "They're already being worked out. Try again in a few minutes.",
      ),
    );
  });

  it("shows read-only quantities and no supplier to staff who only see stock", async () => {
    permissions = new Set(["stock.view"]);
    mockApi({ "/api/v1/reorder-suggestions/": () => page([suggestion({ supplier_name: null })]) });
    renderWithIntl(<SuggestionsPage />);
    const tea = (await screen.findByText("Tata Tea Gold")).closest("tr")!;
    expect(within(tea).queryByRole("textbox")).toBeNull();
    expect(within(tea).getAllByRole("cell").at(-1)).toHaveTextContent("48 PCS");
    expect(screen.queryByRole("columnheader", { name: "Supplier" })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Work out again now" })).toBeNull();
  });

  it("says stock planning is off instead of asking the server", async () => {
    features = new Set();
    const calls = mockApi({});
    renderWithIntl(<SuggestionsPage />);
    expect(screen.getByText("Stock planning isn't switched on")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });
});

const stats = (extra: Partial<ProductStats> = {}): ProductStats => ({
  computed_at: "2026-10-01T00:30:00Z",
  demand_days: 30,
  demand_qty: "60.000",
  per_day: "2.000",
  demand_rate: { quantity: "2.00", period: "DAY" },
  movement_days: 90,
  abc_class: "A",
  movement_class: "FAST",
  last_sale_date: "2026-09-30",
  available: "9.000",
  days_of_stock: "4.0",
  not_selling: false,
  ...extra,
});

describe("ProductPlanningCard", () => {
  it("shows demand, days of stock, classes and what is on order", async () => {
    mockApi({
      "/api/v1/products/p1/stats/": () => [200, stats()],
      "/api/v1/products/p1/on-order/": () => [
        200,
        { quantity: "24.000", expected_date: "2026-10-05", late: true },
      ],
    });
    renderWithIntl(<ProductPlanningCard productId="p1" unit="PCS" />);
    expect(await screen.findByText("A: your top sellers")).toBeInTheDocument();
    expect(screen.getByText("about 2 PCS a day")).toBeInTheDocument();
    expect(screen.getByText("About 4 days")).toBeInTheDocument();
    expect(screen.getByText("Fast")).toBeInTheDocument();
    expect(screen.getByText("Over the last 30 days.")).toBeInTheDocument();
    expect(await screen.findByText(/On order: 24 PCS/)).toHaveTextContent(
      "On order: 24 PCS, expected 05-10-2026Late",
    );
  });

  it("says when stock is out, and when the reorder level looks too high", async () => {
    mockApi({
      "/api/v1/products/p1/stats/": () => [
        200,
        stats({
          available: "0.000",
          days_of_stock: "0.0",
          movement_class: "DEAD",
          abc_class: null,
          not_selling: true,
        }),
      ],
      "/api/v1/products/p1/on-order/": () => [
        200,
        { quantity: "0.000", expected_date: null, late: false },
      ],
    });
    renderWithIntl(<ProductPlanningCard productId="p1" unit="PCS" />);
    expect(await screen.findByText("Out of stock")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Below its reorder level but not selling. Consider lowering the reorder level.",
      ),
    ).toBeInTheDocument();
  });

  it("says when the figures aren't worked out yet", async () => {
    features = new Set(["stock_planning"]);
    mockApi({ "/api/v1/products/p1/stats/": () => [204, undefined] });
    renderWithIntl(<ProductPlanningCard productId="p1" unit="PCS" />);
    expect(
      await screen.findByText("Not worked out yet: they're worked out every night."),
    ).toBeInTheDocument();
  });

  it("is hidden while both modules are off", () => {
    features = new Set();
    const calls = mockApi({});
    const { container } = renderWithIntl(<ProductPlanningCard productId="p1" unit="PCS" />);
    expect(container).toBeEmptyDOMElement();
    expect(calls).toHaveLength(0);
  });
});
