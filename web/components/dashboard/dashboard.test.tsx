import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DistributorDashboard as Body } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { DistributorDashboard } from "./distributor";

const auth = { can: () => false, feature: () => false };
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));

const days = Array.from({ length: 30 }, (_, i) => ({
  date: `2026-09-${String(i + 1).padStart(2, "0")}`,
  billed: i === 29 ? "105.00" : "0.00",
  previous: "0.00",
}));

const owner = (overrides: Partial<Body> = {}): Body => ({
  action: {
    new_orders: 3,
    on_hold: 0,
    backorders_to_confirm: 1,
    to_pack: 2,
    failed_irns: null,
    failed_ewaybills: null,
    handover: { count: 1, amount: "50.00" },
    overdue: { shops: 2, amount: "1600.00" },
    low_stock: { low: 4, out: 1 },
    to_reorder: null,
    late_purchase_orders: null,
    win_back: null,
  },
  today: { orders_received: { count: 3, amount: "420.00" }, billed: "105.00" },
  trends: {
    days,
    billed_30_days: "105.00",
    billed_previous_30_days: "210.00",
    top_products: [{ product_id: "p1", name: "Parle-G", total: "105.00" }],
    top_shops: [],
    new_shops: 2,
    repeat_shops: 5,
  },
  own_shops: false,
  ...overrides,
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("DistributorDashboard", () => {
  it("opens on what needs action, then today, then the last 30 days", async () => {
    mockApi({ "/api/v1/dashboard/": () => [200, owner()] });
    renderWithIntl(<DistributorDashboard />);
    const action = await screen.findByRole("region", { name: "Needs action" });
    expect(within(action).getByRole("link", { name: "New orders: 3" })).toHaveAttribute(
      "href",
      "/manage/orders",
    );
    // Nothing held: shown as all clear, not hidden.
    const hold = within(action).getByRole("link", { name: "Waiting for credit approval: 0" });
    expect(within(hold).getByText("All clear")).toBeInTheDocument();
    const overdue = within(action).getByRole("link", { name: "Shops overdue: 2" });
    expect(overdue).toHaveAttribute("href", "/manage/receivables");
    expect(within(overdue).getByText("₹1,600.00")).toBeInTheDocument();
    expect(within(action).getByRole("link", { name: "Low or out of stock: 5" })).toHaveTextContent(
      "1 out of stock",
    );
    // Modules off: no IRN, e-way bill, reorder or purchase order tiles.
    expect(within(action).queryByText("IRNs failed")).not.toBeInTheDocument();
    expect(within(action).queryByText("Products to reorder")).not.toBeInTheDocument();
    expect(within(action).queryByText("Purchase orders late")).not.toBeInTheDocument();

    const today = screen.getByRole("region", { name: "Today so far" });
    expect(within(today).getByText("₹420.00")).toBeInTheDocument();
    expect(within(today).getByText("3 orders, value incl. GST")).toBeInTheDocument();

    const trends = screen.getByRole("region", { name: "Last 30 days" });
    expect(within(trends).getByText("The 30 days before: ₹210.00")).toBeInTheDocument();
    // The chart's figures are there for screen readers too.
    expect(
      within(trends).getByRole("table", {
        name: "Billed per day: ₹105.00 in the last 30 days, against ₹210.00 in the 30 days before.",
      }),
    ).toBeInTheDocument();
    expect(within(trends).getByRole("link", { name: "Parle-G" })).toHaveAttribute(
      "href",
      "/manage/products/p1",
    );
    expect(within(trends).getByText("No sales this month yet.")).toBeInTheDocument();
    expect(within(trends).getByText("2 new shops")).toBeInTheDocument();
  });

  it("shows reorder and late purchase order tiles while their modules are on", async () => {
    const planning = owner({
      action: { ...owner().action, to_reorder: 6, late_purchase_orders: 2 },
    });
    mockApi({ "/api/v1/dashboard/": () => [200, planning] });
    renderWithIntl(<DistributorDashboard />);
    const action = await screen.findByRole("region", { name: "Needs action" });
    expect(within(action).getByRole("link", { name: "Products to reorder: 6" })).toHaveAttribute(
      "href",
      "/manage/stock/reorder",
    );
    const late = within(action).getByRole("link", { name: "Purchase orders late: 2" });
    expect(late).toHaveAttribute("href", "/manage/purchasing/orders?late=1");
    expect(within(late).getByText("Expected before today")).toBeInTheDocument();
  });

  it("shows the shops to win back, linked to the shop activity list", async () => {
    mockApi({
      "/api/v1/dashboard/": () => [200, owner({ action: { ...owner().action, win_back: 4 } })],
    });
    renderWithIntl(<DistributorDashboard />);
    const action = await screen.findByRole("region", { name: "Needs action" });
    const tile = within(action).getByRole("link", { name: "Shops to win back: 4" });
    expect(tile).toHaveAttribute("href", "/manage/retailers/activity");
  });

  it("shows only what the role may see", async () => {
    const warehouse = owner({
      action: { ...owner().action, handover: null, overdue: null },
      today: { orders_received: { count: 3, amount: "420.00" }, billed: null },
      trends: null,
    });
    mockApi({ "/api/v1/dashboard/": () => [200, warehouse] });
    renderWithIntl(<DistributorDashboard />);
    const action = await screen.findByRole("region", { name: "Needs action" });
    expect(within(action).queryByText("Shops overdue")).not.toBeInTheDocument();
    expect(within(action).queryByText("Collections with salesmen")).not.toBeInTheDocument();
    expect(screen.queryByText("Billed")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Last 30 days" })).not.toBeInTheDocument();
  });

  it("says when figures are only the salesperson's own shops, and shows failures in red", async () => {
    const sales = owner({
      own_shops: true,
      action: { ...owner().action, failed_irns: 2, failed_ewaybills: 0 },
    });
    mockApi({ "/api/v1/dashboard/": () => [200, sales] });
    renderWithIntl(<DistributorDashboard />);
    expect(await screen.findByText("Figures for the shops assigned to you.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "IRNs failed: 2" })).toHaveAttribute(
      "href",
      "/manage/invoices/einvoices",
    );
  });

  it("offers a retry when the dashboard can't load", async () => {
    mockApi({});
    renderWithIntl(<DistributorDashboard />);
    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
