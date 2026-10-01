import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ShopProduct, ShopProductDetail } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { CartProvider } from "./cart-state";
import { CatalogPage, ProductPage } from "./catalog";
import { ShopHome } from "./home";

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

/** Shop screens run inside the cart (the stepper on every product). */
const renderShop = (ui: ReactElement) => renderWithIntl(<CartProvider>{ui}</CartProvider>);

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
  availability: { status: "IN_STOCK", quantity: null },
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
  free_offer: null,
  ...extra,
});

describe("Shop home", () => {
  it("greets the shop, shows categories and the on-hold notice", async () => {
    auth.me.retailer.on_hold = true;
    mockApi({ "/api/v1/shop/categories/": () => [200, tree] });
    renderShop(<ShopHome />);
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
    renderShop(<CatalogPage categoryId="c-food" />);
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
    const { unmount } = renderShop(<ProductPage productId="p1" />);
    expect(await screen.findByText("Buy more, pay less")).toBeVisible();
    const slab = screen.getByText(/24 or more:/).closest("li")!;
    expect(within(slab).getByText("₹9.50")).toBeVisible();
    unmount();

    mockApi({});
    renderShop(<ProductPage productId="gone" />);
    await waitFor(() => expect(screen.getByText("This product isn't available")).toBeVisible());
  });
});

describe("Free goods", () => {
  const offer = {
    scheme_id: "s1",
    name: "Diwali",
    buy_qty: "10.000",
    free_qty: "1.000",
    repeat: true,
    max_free_qty: "3.000",
    same_product: false,
    free_product_name: "Tea 100g",
    free_unit: "PCS",
  };

  it("shows the offer on the product's page", async () => {
    const detail: ShopProductDetail = {
      ...product("p1", "Parle-G", { free_offer: offer }),
      description: "",
      images: [],
      slab_hints: [],
    };
    mockApi({ "/api/v1/shop/products/p1/": () => [200, detail] });
    renderShop(<ProductPage productId="p1" />);
    expect(
      await screen.findByRole("heading", { name: "Buy 10, get 1 Tea 100g free" }),
    ).toBeVisible();
    expect(screen.getByText("For every 10 you buy. Up to 3 free on one order.")).toBeVisible();
  });
});

describe("Stock labels", () => {
  it("shows the server's label, and a quantity only when the distributor allows it", async () => {
    mockApi({
      "/api/v1/shop/categories/": () => [200, tree],
      "/api/v1/shop/brands/": () => [200, []],
      "/api/v1/shop/products/": () => [
        200,
        {
          next: null,
          previous: null,
          results: [
            product("p1", "Parle-G", { availability: { status: "LOW_STOCK", quantity: "3.000" } }),
            product("p2", "Marie", { availability: { status: "BACKORDER", quantity: null } }),
            product("p3", "Monaco", { availability: { status: "OUT_OF_STOCK", quantity: null } }),
          ],
        },
      ],
    });
    renderShop(<CatalogPage />);
    const low = (await screen.findByText("Parle-G")).closest("a")!;
    expect(within(low).getByText("Low stock")).toBeInTheDocument();
    expect(within(low).getByText("3 pieces in stock")).toBeInTheDocument();
    const waiting = screen.getByText("Marie").closest("a")!;
    expect(within(waiting).getByText("Available on backorder")).toBeInTheDocument();
    expect(within(waiting).queryByText(/in stock$/)).not.toBeInTheDocument();
    expect(
      within(screen.getByText("Monaco").closest("a")!).getByText("Out of stock"),
    ).toBeVisible();
  });
});
