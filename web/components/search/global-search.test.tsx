import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SearchResults } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { GlobalSearchProvider, SearchField, SearchIconButton } from "./global-search";

const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/manage" }));

let permissions: string[] = [];
let features: string[] = [];
const auth = {
  me: { id: "u1" },
  can: (code: string) => permissions.includes(code),
  feature: (code: string) => features.includes(code),
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));

const ORDER = {
  type: "order" as const,
  id: "o12",
  title: "ORD-2026-000012",
  detail: "Ganesh Kirana",
  date: "2026-09-30",
  amount: "1250.00",
  status: "PLACED",
};

function results(overrides: Partial<SearchResults> = {}): SearchResults {
  return {
    query: "ord-2026-12",
    jump: ORDER,
    groups: [
      { type: "order", hits: [ORDER], more: false },
      {
        type: "shop",
        hits: [
          {
            type: "shop",
            id: "s1",
            title: "Ganesh Kirana",
            detail: "R-00001",
            date: null,
            amount: null,
            status: "BLOCKED",
          },
        ],
        more: true,
      },
    ],
    ...overrides,
  };
}

function open(scope: "staff" | "platform" = "staff") {
  renderWithIntl(
    <GlobalSearchProvider scope={scope}>
      <SearchField />
      <SearchIconButton />
    </GlobalSearchProvider>,
  );
}

beforeEach(() => {
  permissions = ["orders.view", "invoices.view", "retailers.view"];
  features = [];
  router.push.mockReset();
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GlobalSearch", () => {
  it("opens with Ctrl+K, jumps to a typed number on Enter and remembers the search", async () => {
    const calls = mockApi({ "/api/v1/search/": () => [200, results()] });
    open();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByRole("combobox", { name: "Search" });
    await userEvent.type(input, "ord-2026-12");
    const best = await screen.findByText("Best match");
    expect(best).toBeInTheDocument();
    const options = screen.getAllByRole("option");
    expect(options[0]).toHaveTextContent("ORD-2026-000012");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(within(options[0]!).getByText("₹1,250.00")).toBeInTheDocument();
    // The order is shown once (as the best match), the shop with its status and "See all".
    expect(screen.getAllByText("ORD-2026-000012")).toHaveLength(1);
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /See all Shops/ })).toBeInTheDocument();
    expect(calls.at(-1)?.url.searchParams.get("q")).toBe("ord-2026-12");
    await userEvent.keyboard("{Enter}");
    expect(router.push).toHaveBeenCalledWith("/manage/orders/o12");
    expect(JSON.parse(window.localStorage.getItem("search.recent.u1") ?? "[]")).toEqual([
      "ord-2026-12",
    ]);
  });

  it("moves with the arrows and opens a list with the same search", async () => {
    mockApi({ "/api/v1/search/": () => [200, results()] });
    open();
    await userEvent.click(screen.getByRole("button", { name: /Search…/ }));
    await userEvent.type(screen.getByRole("combobox"), "ord-2026-12");
    await screen.findByText("Best match");
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    const seeAll = screen.getByRole("option", { name: /See all Shops/ });
    expect(seeAll).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Enter}");
    expect(router.push).toHaveBeenCalledWith("/manage/retailers?q=ord-2026-12");
  });

  it("finds pages and settings by name, only those the person may open", async () => {
    mockApi({ "/api/v1/search/": () => [200, results({ jump: null, groups: [] })] });
    open();
    await userEvent.click(screen.getByRole("button", { name: /Search…/ }));
    await userEvent.type(screen.getByRole("combobox"), "credit");
    expect(await screen.findByRole("option", { name: "Credit notes" })).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument(); // e.g. the credit settings
    await userEvent.clear(screen.getByRole("combobox"));
    await userEvent.type(screen.getByRole("combobox"), "e-way");
    // E-way bills need the module and compliance.manage.
    await waitFor(() => expect(screen.queryByRole("option", { name: "E-way bills" })).toBeNull());
    expect(await screen.findByText(/Nothing found for “e-way”/)).toBeInTheDocument();
  });

  it("shows recent searches before anything is typed", async () => {
    window.localStorage.setItem("search.recent.u1", JSON.stringify(["ganesh", "INV/26-27/7"]));
    mockApi({ "/api/v1/search/": () => [200, results({ jump: null, groups: [] })] });
    open();
    await userEvent.click(screen.getByRole("button", { name: /Search…/ }));
    expect(screen.getByText("Recent searches")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: "INV/26-27/7" }));
    expect(screen.getByRole("combobox")).toHaveValue("INV/26-27/7");
  });

  it("says when search fails and offers to try again", async () => {
    mockApi({
      "/api/v1/search/": () => [
        500,
        { error: { code: "INTERNAL_ERROR", message: "", details: {} } },
      ],
    });
    open();
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await userEvent.type(screen.getByRole("combobox"), "ganesh");
    expect(await screen.findByText("Search isn't working right now.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("finds people across distributors only when asked (each search is audited)", async () => {
    permissions = ["platform.tenants.manage"];
    const calls = mockApi({
      "/api/v1/platform/search/": () => [
        200,
        {
          query: "ganesh",
          jump: null,
          groups: [
            {
              type: "tenant",
              hits: [
                {
                  type: "tenant",
                  id: "t1",
                  title: "Sharma Distributors",
                  detail: "sharma",
                  date: null,
                  amount: null,
                  status: "ACTIVE",
                },
              ],
              more: false,
            },
          ],
        },
      ],
      "/api/v1/platform/search/users/": () => [
        200,
        [
          {
            kind: "SHOP",
            id: "p1",
            name: "Ganesh Patil",
            email: "",
            phone: "+919876500101",
            tenant_id: "t1",
            tenant_name: "Sharma Distributors",
            shop_name: "Ganesh Kirana",
            is_active: true,
          },
        ],
      ],
    });
    open("platform");
    await userEvent.click(screen.getByRole("button", { name: /Search…/ }));
    await userEvent.type(screen.getByRole("combobox"), "ganesh");
    expect(await screen.findByRole("option", { name: /Sharma Distributors/ })).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/v1/platform/search/users/")).toBe(false);
    await userEvent.click(screen.getByRole("option", { name: /Find people named “ganesh”/ }));
    const person = await screen.findByRole("option", { name: /Ganesh Kirana \(Ganesh Patil\)/ });
    await userEvent.click(person);
    expect(router.push).toHaveBeenCalledWith("/platform/tenants/t1");
  });
});
