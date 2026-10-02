import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AssistantQuestion } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { Assistant } from "./assistant";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const TOOLS = {
  tools: [
    { name: "shops_not_ordering", report: "shop_activity" },
    { name: "dues", report: "receivables_ageing" },
  ],
};

const answered: AssistantQuestion = {
  id: "q1",
  question: "Which shops haven't ordered in 30 days?",
  status: "ANSWERED",
  answer: "2 shops haven't ordered in 30 days or more. Longest gaps: Durga Traders (45 days).",
  tools: [
    {
      name: "shops_not_ordering",
      args: { days: 30 },
      ok: true,
      figures: {
        tool: "shops_not_ordering",
        report: "shop_activity",
        title: "Shop activity",
        date_from: null,
        date_to: null,
        columns: [
          { key: "name", label: "Shop", kind: "text" },
          { key: "days_since", label: "Days since", kind: "int" },
        ],
        rows: [
          { name: "Durga Traders", days_since: 45, retailer_id: "r1" },
          { name: "Chamunda Kirana", days_since: null, retailer_id: "r2" },
        ],
        totals: null,
        count: 5,
        own_shops: true,
        notes: [],
      },
    },
  ],
  created_at: "2026-10-02T05:00:00Z",
  answered_at: "2026-10-02T05:00:02Z",
};

describe("Assistant", () => {
  it("shows the answer with the figures it came from", async () => {
    mockApi({
      "/api/v1/assistant/tools/": () => [200, TOOLS],
      "/api/v1/assistant/questions/": () => [
        200,
        { next: null, previous: null, results: [answered] },
      ],
    });
    renderWithIntl(<Assistant />);
    expect(await screen.findByText(/Longest gaps: Durga Traders/)).toBeInTheDocument();
    const figures = screen.getByRole("region", { name: "Shop activity" });
    expect(within(figures).getAllByRole("link", { name: "Durga Traders" })[0]).toHaveAttribute(
      "href",
      "/manage/retailers/r1",
    );
    expect(within(figures).getByText("Only your shops.")).toBeInTheDocument();
    expect(
      within(figures).getByText("Showing 2 of 5. Open the report for all of them."),
    ).toBeInTheDocument();
    // Only the suggestions for tools this person may use.
    expect(screen.getByRole("button", { name: "Who owes us the most money?" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Which products are running low?" }),
    ).not.toBeInTheDocument();
  });

  it("asks a suggested question and waits for the answer", async () => {
    const pending: AssistantQuestion = {
      ...answered,
      id: "q2",
      question: "Who owes us the most money?",
      status: "PENDING",
      answer: "",
      tools: [],
      answered_at: null,
    };
    let asked = false;
    const calls = mockApi({
      "/api/v1/assistant/tools/": () => [200, TOOLS],
      "POST /api/v1/assistant/questions/": () => {
        asked = true;
        return [202, pending];
      },
      "/api/v1/assistant/questions/": () => [
        200,
        { next: null, previous: null, results: asked ? [pending] : [] },
      ],
      "/api/v1/assistant/questions/q2/": () => [200, pending],
    });
    renderWithIntl(<Assistant />);
    expect(await screen.findByText("No questions yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Who owes us the most money?" }));
    const posted = calls.filter((c) => c.method === "POST").map((c) => c.body);
    expect(posted).toEqual([{ question: "Who owes us the most money?" }]);
    expect(await screen.findByText("Looking at your figures…")).toBeInTheDocument();
  });

  it("explains when there is nothing to ask about, and failed answers", async () => {
    mockApi({
      "/api/v1/assistant/tools/": () => [200, { tools: [] }],
      "/api/v1/assistant/questions/": () => [200, { next: null, previous: null, results: [] }],
    });
    const { unmount } = renderWithIntl(<Assistant />);
    expect(await screen.findByText("Nothing to ask about")).toBeInTheDocument();
    unmount();
    mockApi({
      "/api/v1/assistant/tools/": () => [200, TOOLS],
      "/api/v1/assistant/questions/": () => [
        200,
        { next: null, previous: null, results: [{ ...answered, status: "LIMITED", tools: [] }] },
      ],
    });
    renderWithIntl(<Assistant />);
    expect(await screen.findByText(/allowance is used up/)).toBeInTheDocument();
  });
});
