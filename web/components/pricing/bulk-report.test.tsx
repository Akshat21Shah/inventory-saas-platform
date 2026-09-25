import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { BulkAdjustDialog } from "./bulk-adjust";
import { ShopPricingReportPage } from "./shop-report";

const auth = { me: { id: "u1" }, can: () => true };
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/manage/pricing",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => vi.unstubAllGlobals());

const empty = { next: null, previous: null, results: [] };

describe("Bulk % change", () => {
  it("previews on the server, then applies exactly the previewed count", async () => {
    const preview = {
      count: 2,
      added: 1,
      rows: [
        { code: "A", name: "Atta", old: "9.00", new: "9.45" },
        { code: "C", name: "Chips", old: null, new: "35.00" },
      ],
    };
    const calls = mockApi({
      "/api/v1/categories/tree/": () => [200, []],
      "/api/v1/brands/": () => [200, { ...empty, results: [{ id: "b1", name: "Lays" }] }],
      "POST /api/v1/price-lists/pl1/adjust/preview/": () => [200, preview],
      "POST /api/v1/price-lists/pl1/adjust/": () => [200, { changed: 2, warnings: [] }],
    });
    const done = vi.fn();
    renderWithIntl(<BulkAdjustDialog priceListId="pl1" listName="Gold" onDone={done} />);
    await userEvent.click(screen.getByRole("button", { name: "Change prices by %" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Change \(%\)/), "+5");
    await userEvent.click(within(dialog).getByRole("combobox", { name: /^Brand/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Lays" }));
    await userEvent.click(within(dialog).getByRole("checkbox"));
    await userEvent.click(within(dialog).getByRole("combobox", { name: /Round to/ }));
    await userEvent.click(await screen.findByRole("option", { name: /Whole rupees/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Preview" }));
    expect(
      await within(dialog).findByText("2 prices will change (1 new on the list)."),
    ).toBeVisible();
    await userEvent.click(within(dialog).getByRole("button", { name: "Update 2 prices" }));
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(calls.find((c) => c.path === "/api/v1/price-lists/pl1/adjust/")?.body).toEqual({
      percent: "5",
      category: null,
      brand: "b1",
      include_missing: true,
      rounding: "RUPEE",
      expected_count: 2,
    });
  });
});

describe("Shop pricing report", () => {
  it("lists shops with their own pricing and shows the products they get free", async () => {
    mockApi({
      "/api/v1/pricing/shop-report/": () => [
        200,
        {
          ...empty,
          results: [
            {
              id: "r1",
              code: "R-00001",
              shop_name: "Ganesh",
              price_list: { id: "pl1", name: "Gold" },
              special_price_count: 3,
              shop_rule_count: 2,
              free_product_count: 1,
            },
          ],
        },
      ],
      "/api/v1/retailers/r1/free-products/": () => [
        200,
        [{ id: "p1", code: "PG-100", name: "Parle-G" }],
      ],
    });
    renderWithIntl(<ShopPricingReportPage />);
    const row = (await screen.findByText("Ganesh")).closest("tr")!;
    expect(within(row).getByText("Gold")).toBeVisible();
    expect(within(row).getByRole("link", { name: "3" })).toHaveAttribute(
      "href",
      "/manage/pricing/special-prices?retailer=r1",
    );
    await userEvent.click(within(row).getByRole("button", { name: "1" }));
    expect(await screen.findByText("Parle-G (PG-100)")).toBeVisible();
  });
});
