import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DiscountRule, RetailerPrice } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { NewDiscountRulePage } from "./discounts";
import { PriceListDetailPage } from "./price-lists";
import { SpecialPricesPage } from "./special-prices";

const auth = { me: { id: "u1" }, can: () => true };
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/manage/pricing",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  router.push.mockReset();
});

const empty = { next: null, previous: null, results: [] };
const lookups = {
  "/api/v1/categories/tree/": () => [200, []] as [number, unknown],
  "/api/v1/brands/": () => [200, empty] as [number, unknown],
  "/api/v1/price-lists/": () =>
    [200, { ...empty, results: [{ id: "pl-gold", name: "Gold" }] }] as [number, unknown],
};

const freeGoods = {
  code: "FREE_GOODS",
  message: "server text",
  details: { products: 3, retailers: 2 },
};

const savedRule = (warnings: DiscountRule["warnings"]): DiscountRule => ({
  id: "rule-1",
  name: "Bulk",
  discount_type: "PERCENT",
  value: "0.00",
  scope_type: "ALL",
  product: null,
  category: null,
  brand: null,
  audience_type: "PRICE_LIST",
  price_list: { id: "pl-gold", name: "Gold" },
  retailer: null,
  valid_from: null,
  valid_to: null,
  is_active: true,
  slabs: [{ min_qty: "12.000", value: "100.00" }],
  created_at: "2026-09-25T10:00:00Z",
  updated_at: "2026-09-25T10:00:00Z",
  warnings,
});

describe("Discount rule editor", () => {
  it("sends slabs as typed, shows the free-goods warning and keeps editing the saved rule", async () => {
    const calls = mockApi({
      ...lookups,
      "POST /api/v1/discount-rules/": () => [201, savedRule([freeGoods])],
      "PATCH /api/v1/discount-rules/rule-1/": () => [200, savedRule([])],
    });
    renderWithIntl(<NewDiscountRulePage />);
    await userEvent.type(await screen.findByLabelText(/^Name/), "Bulk");
    await userEvent.click(screen.getByRole("switch", { name: /Bigger discount/ }));
    await userEvent.type(screen.getByLabelText("From quantity"), "12");
    await userEvent.type(screen.getByLabelText("Discount (%)"), "100");
    await userEvent.click(screen.getByRole("combobox", { name: /^For/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Shops on a price list" }));
    await userEvent.click(screen.getByRole("combobox", { name: /Shops on a price list/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Gold" }));
    await userEvent.click(screen.getByRole("button", { name: "Add discount" }));

    expect(
      await screen.findByText(
        "This rule makes 3 products free for 2 retailers. Free-goods schemes are not supported yet.",
      ),
    ).toBeVisible();
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      name: "Bulk",
      discount_type: "PERCENT",
      value: "0",
      slabs: [{ min_qty: "12", value: "100" }],
      audience_type: "PRICE_LIST",
      price_list: "pl-gold",
      scope_type: "ALL",
    });
    expect(router.push).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/manage/pricing/discounts"));
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
    expect(calls.some((c) => c.method === "PATCH")).toBe(true);
  });
});

describe("Special prices", () => {
  it("picks a shop and product by searching, and words the warning for one shop", async () => {
    const saved: RetailerPrice = {
      id: "sp1",
      retailer: { id: "r1", code: "R-00001", shop_name: "Ganesh Kirana" },
      product: { id: "p1", code: "PG-100", name: "Parle-G" },
      base_price: "10.00",
      price: "0.00",
      note: "",
      updated_at: "2026-09-25T10:00:00Z",
      warnings: [{ ...freeGoods, details: { products: 1, retailers: 1 } }],
    };
    const calls = mockApi({
      "/api/v1/retailer-prices/": () => [200, empty],
      "/api/v1/retailers/": () => [
        200,
        { ...empty, results: [{ id: "r1", code: "R-00001", shop_name: "Ganesh Kirana" }] },
      ],
      "/api/v1/products/search/": () => [200, [{ id: "p1", code: "PG-100", name: "Parle-G" }]],
      "POST /api/v1/retailer-prices/": () => [201, saved],
    });
    renderWithIntl(<SpecialPricesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Add special price" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByRole("combobox", { name: /Shop/ }), "gan");
    await userEvent.click(await within(dialog).findByRole("option", { name: /Ganesh Kirana/ }));
    await userEvent.type(within(dialog).getByRole("combobox", { name: /Product/ }), "parle");
    await userEvent.click(await within(dialog).findByRole("option", { name: /Parle-G/ }));
    await userEvent.type(within(dialog).getByLabelText(/Special price/), "0");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText(
        "This special price makes this product free for this retailer. Free-goods schemes are not supported yet.",
      ),
    ).toBeVisible();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      retailer: "r1",
      product: "p1",
      price: "0",
      note: "",
    });
  });
});

describe("Price list items", () => {
  it("saves an edited list price as the string typed", async () => {
    const calls = mockApi({
      "/api/v1/price-lists/pl-gold/": () => [
        200,
        { id: "pl-gold", name: "Gold", item_count: 1, shop_count: 3, created_at: "2026-09-25" },
      ],
      "/api/v1/price-lists/pl-gold/items/": () => [
        200,
        {
          ...empty,
          results: [
            {
              product: { id: "p1", code: "PG-100", name: "Parle-G" },
              unit: "PCS",
              base_price: "10.00",
              price: "9.00",
              updated_at: "2026-09-25T10:00:00Z",
            },
          ],
        },
      ],
      "PUT /api/v1/price-lists/pl-gold/items/": () => [200, { changed: 1 }],
    });
    renderWithIntl(<PriceListDetailPage priceListId="pl-gold" />);
    const input = await screen.findByRole("textbox", { name: "List price for Parle-G" });
    await userEvent.clear(input);
    await userEvent.type(input, "1,008.50");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        items: [{ product: "p1", price: "1008.50" }],
      }),
    );
  });
});
