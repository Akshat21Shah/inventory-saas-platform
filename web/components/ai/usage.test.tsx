import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MyAiUsage, TenantAiUsage } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { AiUsageCard, PlatformAiUsage } from "./usage";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const mine = (overrides: Partial<MyAiUsage> = {}): MyAiUsage => ({
  enabled: true,
  since: "2026-10-01",
  units: 1_850_000,
  limit: 2_000_000,
  calls: 41,
  failed: 1,
  near_limit: true,
  by_feature: [
    { feature: "SEARCH_INDEX", units: 1_800_000, calls: 4, failed: 0 },
    { feature: "SEARCH_QUERY", units: 50_000, calls: 37, failed: 1 },
  ],
  ...overrides,
});

describe("AiUsageCard", () => {
  it("shows this month's units against the limit, by feature", async () => {
    mockApi({ "/api/v1/settings/ai-usage/": () => [200, mine()] });
    renderWithIntl(<AiUsageCard />);
    expect(await screen.findByText("18,50,000 of 20,00,000 units")).toBeInTheDocument();
    expect(screen.getByText("Near a limit")).toBeInTheDocument();
    expect(screen.getByText(/Since 01-10-2026/)).toBeInTheDocument();
    const shops = screen.getByText("Shop search: what shops typed").closest("li")!;
    expect(within(shops).getByText("50,000 units · 37 requests · 1 failed")).toBeInTheDocument();
  });

  it("says when there is no limit and nothing used", async () => {
    mockApi({
      "/api/v1/settings/ai-usage/": () => [
        200,
        mine({ units: 0, limit: null, calls: 0, failed: 0, near_limit: false, by_feature: [] }),
      ],
    });
    renderWithIntl(<AiUsageCard />);
    expect(await screen.findByText("0 units")).toBeInTheDocument();
    expect(screen.getByText("No monthly limit")).toBeInTheDocument();
    expect(screen.getByText("Nothing used yet this month.")).toBeInTheDocument();
    expect(screen.queryByText("Near a limit")).not.toBeInTheDocument();
  });
});

describe("PlatformAiUsage", () => {
  const rows: TenantAiUsage[] = [
    {
      tenant_id: "t1",
      name: "Sharma Distributors",
      units: 1_900_000,
      calls: 120,
      failed: 2,
      limit: 2_000_000,
      near_limit: true,
    },
    {
      tenant_id: "t2",
      name: "Patel Traders",
      units: 4_000,
      calls: 9,
      failed: 0,
      limit: 2_000_000,
      near_limit: false,
    },
  ];

  it("lists each distributor's use, linked to the distributor", async () => {
    mockApi({ "/api/v1/platform/ai-usage/": () => [200, rows] });
    renderWithIntl(<PlatformAiUsage />);
    const link = await screen.findByRole("link", { name: "Sharma Distributors" });
    expect(link).toHaveAttribute("href", "/platform/tenants/t1");
    expect(screen.getByText("19,00,000 of 20,00,000")).toBeInTheDocument();
    expect(screen.getAllByText("Near a limit")).toHaveLength(1);
  });

  it("says when nobody used AI this month", async () => {
    mockApi({ "/api/v1/platform/ai-usage/": () => [200, []] });
    renderWithIntl(<PlatformAiUsage />);
    expect(await screen.findByText("No AI use this month.")).toBeInTheDocument();
  });
});
