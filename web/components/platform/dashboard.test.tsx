import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Dashboard } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { PlatformDashboard } from "./dashboard";

const body = (overrides: Partial<Dashboard> = {}): Dashboard => ({
  total: 3,
  active: 2,
  onboarding: 0,
  suspended: 1,
  orders_per_day: Array.from({ length: 30 }, (_, i) => ({
    date: `2026-09-${String(i + 1).padStart(2, "0")}`,
    count: i === 29 ? 4 : 0,
    value: i === 29 ? "840.00" : "0.00",
  })),
  top_tenants: [{ tenant_id: "t1", name: "Sharma Distributors", orders: 4, value: "840.00" }],
  failures: [
    {
      tenant_id: "t2",
      name: "Patel Traders",
      failed_messages: 3,
      failed_irns: 0,
      failed_ewaybills: 1,
      gst_login_failed: false,
      gateway_failed: true,
    },
  ],
  usage: [
    {
      tenant_id: "t1",
      name: "Sharma Distributors",
      plan: "Small",
      shops: 46,
      staff: 5,
      products: 200,
      max_shops: 50,
      max_staff: null,
      max_products: 1000,
      near_limit: true,
    },
  ],
  errors_24h: { requests: 1200, server_errors: 3, rate: "0.25" },
  ...overrides,
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PlatformDashboard", () => {
  it("shows orders across distributors, the top ones, failures, usage and errors", async () => {
    mockApi({ "/api/v1/platform/dashboard/": () => [200, body()] });
    renderWithIntl(<PlatformDashboard />);
    expect(await screen.findByText("All distributors")).toBeInTheDocument();

    const orders = screen.getByRole("region", { name: "Orders across distributors" });
    expect(
      within(orders).getByRole("table", {
        name: "Value of orders placed per day across all distributors, last 30 days",
      }),
    ).toBeInTheDocument();

    const top = screen.getByRole("region", { name: "Top distributors" });
    expect(within(top).getAllByRole("link", { name: "Sharma Distributors" })[0]).toHaveAttribute(
      "href",
      "/platform/tenants/t1",
    );

    const failing = screen.getByRole("region", { name: "Something failing" });
    expect(within(failing).getAllByText("Payment gateway").length).toBeGreaterThan(0);
    expect(within(failing).queryByText("GST login")).not.toBeInTheDocument();

    const usage = screen.getByRole("region", { name: "Usage against plans" });
    expect(within(usage).getAllByText("46 of 50").length).toBeGreaterThan(0);
    expect(within(usage).getAllByText("Near a limit").length).toBeGreaterThan(0);

    const errors = screen.getByRole("region", { name: "Errors in the last 24 hours" });
    expect(within(errors).getByText("0.25%")).toBeInTheDocument();
    expect(within(errors).getByText("3 server errors in 1,200 requests")).toBeInTheDocument();
  });

  it("says so when nothing is failing and there were no requests yet", async () => {
    mockApi({
      "/api/v1/platform/dashboard/": () => [
        200,
        body({ failures: [], errors_24h: { requests: 0, server_errors: 0, rate: null } }),
      ],
    });
    renderWithIntl(<PlatformDashboard />);
    expect(await screen.findByText("Nothing failing")).toBeInTheDocument();
    const errors = screen.getByRole("region", { name: "Errors in the last 24 hours" });
    expect(within(errors).getByText("—")).toBeInTheDocument();
  });

  it("lists those near a plan limit and the first few others, then all on request", async () => {
    const many = Array.from({ length: 14 }, (_, i) => ({
      ...body().usage[0]!,
      tenant_id: `t${i}`,
      name: `Distributor ${i}`,
      near_limit: i === 12,
    }));
    mockApi({ "/api/v1/platform/dashboard/": () => [200, body({ usage: many })] });
    renderWithIntl(<PlatformDashboard />);
    const usage = await screen.findByRole("region", { name: "Usage against plans" });
    expect(within(usage).getAllByRole("link", { name: /^Distributor/ })).toHaveLength(11);
    expect(within(usage).getAllByRole("link", { name: "Distributor 12" })).toHaveLength(1);
    await userEvent.click(within(usage).getByRole("button", { name: "Show all 14" }));
    expect(within(usage).getAllByRole("link", { name: /^Distributor/ })).toHaveLength(14);
  });

  it("offers a retry when it can't load", async () => {
    mockApi({});
    renderWithIntl(<PlatformDashboard />);
    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
