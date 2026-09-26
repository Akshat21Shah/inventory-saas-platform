import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ShopProduct, ShopProductDetail } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { CatalogPage, ProductPage, ShopHome } from "./catalog";

const auth: { me: { retailer: { shop_name: string; on_hold: boolean } } } = {
  me: { retailer: { shop_name: "Ganesh Kirana", on_hold: false } },
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const router = { replace: vi.fn(), push: vi.fn(), back: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/shop",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  auth.me.retailer.on_hold = false;
});

const tree = [
  {
    id: "c-food",
    name: "Food",
    level: 1,
    product_count: 2,
    children: [{ id: "c-bis", name: "Biscuits", level: 2, product_count: 2, children: [] }],
  },
];

const product = (id: string, name: string, extra: Partial<ShopProduct> = {}): ShopProduct => ({
  id,
  code: id,
  name,
  brand: { id: "b1", name: "Parle" },
  category: { id: "c-bis", name: "Biscuits" },
  unit: { code: "PCS", name: "pieces" },
  pack_unit: null,
  pack_size: null,
  mrp: "12.00",
  min_order_qty: "1.000",
  order_multiple: "1.000",
  thumbnail_url: null,
  own_brand: false,
  price: {
    qty: "1.000",
    unit_price: "10.00",
    discount_total: "0.00",
    discount_percent: "0.00",
    discount_per_unit: "0.00",
    net_unit_price: "10.00",
    gst_rate: "18.000",
    prices_include_gst: false,
  },
  ...extra,
});

describe("Shop home", () => {
  it("greets the shop, shows categories and the on-hold notice", async () => {
    auth.me.retailer.on_hold = true;
    mockApi({ "/api/v1/shop/categories/": () => [200, tree] });
    renderWithIntl(<ShopHome />);
    expect(screen.getByRole("heading", { name: "Hello, Ganesh Kirana" })).toBeVisible();
    expect(
      screen.getByText("Your account is on hold. Please contact your distributor."),
    ).toBeVisible();
    const food = await screen.findByRole("link", { name: /Food/ });
    expect(food).toHaveAttribute("href", "/shop/catalog/c-food");
    expect(within(food).getByText("2 products")).toBeVisible();
  });
});

describe("Catalog", () => {
  it("shows the server's prices with discount, MRP and GST, and loads more", async () => {
    let page = 0;
    mockApi({
      "/api/v1/shop/categories/": () => [200, tree],
      "/api/v1/shop/brands/": () => [200, [{ id: "b1", name: "Parle" }]],
      "/api/v1/shop/products/": (_body, url) => {
        page += 1;
        return url.searchParams.get("cursor")
          ? [200, { next: null, previous: null, results: [product("p3", "Monaco")] }]
          : [
              200,
              {
                next: "http://x/api/v1/shop/products/?cursor=abc",
                previous: null,
                results: [
                  product("p1", "Parle-G", {
                    min_order_qty: "6.000",
                    order_multiple: "6.000",
                    price: {
                      qty: "6.000",
                      unit_price: "10.00",
                      discount_total: "3.00",
                      discount_percent: "5.00",
                      discount_per_unit: "0.50",
                      net_unit_price: "9.50",
                      gst_rate: "18.000",
                      prices_include_gst: false,
                    },
                  }),
                  product("p2", "Krackjack"),
                ],
              },
            ];
      },
    });
    renderWithIntl(<CatalogPage categoryId="c-food" />);
    const parle = (await screen.findByText("Parle-G")).closest("a")!;
    expect(within(parle).getByText("₹9.50")).toBeVisible();
    expect(within(parle).getByText("₹10.00")).toHaveClass("line-through");
    const saving = within(parle).getByText(/You save/);
    expect(saving).toHaveTextContent("You save ₹0.50 each (5%)");
    expect(within(parle).getByText("+ 18% GST")).toBeVisible();
    expect(within(parle).getByText("₹12.00")).toBeVisible();
    expect(within(parle).getByText("Order at least 6 pieces · in steps of 6")).toBeVisible();
    expect(screen.getByRole("link", { name: /Biscuits/ })).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(await screen.findByText("Monaco")).toBeVisible();
    expect(page).toBe(2);
  });
});

describe("Product page", () => {
  it("shows slab hints and says clearly when a product isn't available", async () => {
    const detail: ShopProductDetail = {
      ...product("p1", "Parle-G"),
      description: "Glucose biscuits",
      images: [],
      slab_hints: [{ min_qty: "24.000", net_unit_price: "9.50" }],
    };
    mockApi({ "/api/v1/shop/products/p1/": () => [200, detail] });
    const { unmount } = renderWithIntl(<ProductPage productId="p1" />);
    expect(await screen.findByText("Buy more, pay less")).toBeVisible();
    const slab = screen.getByText(/24 or more:/).closest("li")!;
    expect(within(slab).getByText("₹9.50")).toBeVisible();
    unmount();

    mockApi({});
    renderWithIntl(<ProductPage productId="gone" />);
    await waitFor(() => expect(screen.getByText("This product isn't available")).toBeVisible());
  });
});
