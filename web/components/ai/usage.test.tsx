import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MyAiUsage, PlatformAiUsage as PlatformBody } from "@/lib/api/generated/model";
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
  model: "claude-sonnet-5-5",
  cost: "590.40",
  questions: 287,
  searches: 4210,
  allowance: { questions: 333, searches: 100_000, cost: "636.00" },
  units: 1_850_000,
  limit: 2_000_000,
  calls: 1180,
  failed: 1,
  near_limit: true,
  by_feature: [
    { feature: "ASSISTANT", cost: "590.28", units: 1_790_000, calls: 960, failed: 0 },
    { feature: "SEARCH_QUERY", cost: "0.12", units: 60_000, calls: 4211, failed: 1 },
  ],
  ...overrides,
});

describe("AiUsageCard", () => {
  it("shows the month in rupees, questions and searches against the allowance", async () => {
    mockApi({ "/api/v1/settings/ai-usage/": () => [200, mine()] });
    renderWithIntl(<AiUsageCard />);
    expect(await screen.findByText("₹590.40 of about ₹636.00")).toBeInTheDocument();
    expect(screen.getByText("Near a limit")).toBeInTheDocument();
    expect(
      screen.getByText(/Estimated at today's prices for Claude Sonnet 5.5/),
    ).toBeInTheDocument();
    expect(screen.getByText("287 questions to the assistant")).toBeInTheDocument();
    expect(screen.getByText("4,210 shop searches")).toBeInTheDocument();
    expect(screen.getByText("about 333 assistant questions")).toBeInTheDocument();
    expect(screen.getByText("or about 1,00,000 shop searches")).toBeInTheDocument();
    const shops = screen.getByText("Shop search: what shops typed").closest("li")!;
    expect(within(shops).getByText("₹0.12 · 4,211 requests · 1 failed")).toBeInTheDocument();
    expect(screen.queryByText(/18,50,000|1,850,000/)).not.toBeInTheDocument(); // units stay inside
  });

  it("says when there is no limit and nothing used", async () => {
    mockApi({
      "/api/v1/settings/ai-usage/": () => [
        200,
        mine({
          cost: "0.00",
          questions: 0,
          searches: 0,
          allowance: null,
          limit: null,
          near_limit: false,
          by_feature: [],
        }),
      ],
    });
    renderWithIntl(<AiUsageCard />);
    expect(await screen.findByText("₹0.00")).toBeInTheDocument();
    expect(screen.getByText("No monthly limit")).toBeInTheDocument();
    expect(screen.getByText("Nothing used yet this month.")).toBeInTheDocument();
    expect(screen.queryByText("Near a limit")).not.toBeInTheDocument();
  });
});

describe("PlatformAiUsage", () => {
  const body: PlatformBody = {
    model: "claude-haiku-4-5-20251001",
    limit: 2_000_000,
    allowance: { questions: 333, searches: 100_000, cost: "211.20" },
    rows: [
      {
        tenant_id: "t1",
        name: "Sharma Distributors",
        cost: "190.50",
        questions: 290,
        searches: 3100,
        units: 1_900_000,
        calls: 120,
        failed: 2,
        near_limit: true,
      },
      {
        tenant_id: "t2",
        name: "Patel Traders",
        cost: "4.00",
        questions: 6,
        searches: 40,
        units: 4_000,
        calls: 9,
        failed: 0,
        near_limit: false,
      },
    ],
  };

  it("lists each distributor's estimated cost, questions and searches against the allowance", async () => {
    mockApi({ "/api/v1/platform/ai-usage/": () => [200, body] });
    renderWithIntl(<PlatformAiUsage />);
    const link = await screen.findByRole("link", { name: "Sharma Distributors" });
    expect(link).toHaveAttribute("href", "/platform/tenants/t1");
    expect(screen.getByText("₹190.50 of ₹211.20")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Each distributor may use about 333 assistant questions or 1,00,000 shop searches a month, at most about ₹211.20 (priced at Claude Haiku 4.5; prices are platform settings).",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Near a limit")).toHaveLength(1);
  });

  it("says when nobody used AI this month", async () => {
    mockApi({ "/api/v1/platform/ai-usage/": () => [200, { ...body, rows: [] }] });
    renderWithIntl(<PlatformAiUsage />);
    expect(await screen.findByText("No AI use this month.")).toBeInTheDocument();
  });
});
