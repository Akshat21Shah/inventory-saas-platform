import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ProductDetail, ProductList } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { CategoriesPage } from "./masters";
import { EditProductPage, NewProductPage } from "./product-editor";
import { ProductsPage } from "./products-page";

const permissions = new Set([
  "products.view",
  "products.manage",
  "pricing.view",
  "pricing.manage",
  "costs.view",
  "costs.manage",
]);
const features = new Set<string>();
const auth = {
  me: { id: "u1" },
  can: (p: string) => permissions.has(p),
  feature: (code: string) => features.has(code),
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/manage" }));

afterEach(() => {
  vi.unstubAllGlobals();
  for (const p of [
    "products.manage",
    "pricing.view",
    "pricing.manage",
    "costs.view",
    "costs.manage",
  ])
    permissions.add(p);
});

const row = (code: string, name: string, extra: Partial<ProductList> = {}): ProductList => ({
  id: `id-${code}`,
  code,
  name,
  category: { id: "c-bis", name: "Biscuits" },
  brand: { id: "b-parle", name: "Parle" },
  unit: "PCS",
  hsn_code: "1905",
  gst_rate: "18.000",
  mrp: "10.00",
  base_price: "8.50",
  is_active: true,
  show_in_shop: true,
  own_brand: false,
  thumbnail_url: null,
  ...extra,
});

const tree = [
  {
    id: "c-food",
    name: "Food",
    level: 1,
    sort_order: 0,
    children: [{ id: "c-bis", name: "Biscuits", level: 2, sort_order: 0, children: [] }],
  },
];

const masters = {
  "/api/v1/categories/tree/": () => [200, tree] as [number, unknown],
  "/api/v1/brands/": () =>
    [200, { next: null, previous: null, results: [{ id: "b-parle", name: "Parle" }] }] as [
      number,
      unknown,
    ],
  "/api/v1/units/": () =>
    [
      200,
      {
        next: null,
        previous: null,
        results: [{ id: "u-pcs", code: "PCS", name: "Pieces", uqc: "NOS", is_active: true }],
      },
    ] as [number, unknown],
  "/api/v1/products/tax-options/": () =>
    [
      200,
      {
        gst_rates: [
          { rate: "5.000", label: "5%" },
          { rate: "18.000", label: "18%" },
        ],
        cess_types: [],
      },
    ] as [number, unknown],
  "/api/v1/products/hsn-hint/": () => [200, { hint: null }] as [number, unknown],
};

describe("ProductsPage", () => {
  it("lists products with money and GST formatted, and filters on the server", async () => {
    const calls = mockApi({
      ...masters,
      "/api/v1/products/": () => [
        200,
        {
          next: null,
          previous: null,
          results: [row("PG-100", "Parle-G 100g"), row("HD-1", "Hide me", { show_in_shop: false })],
        },
      ],
    });
    renderWithIntl(<ProductsPage />);
    const parle = (await screen.findByText("Parle-G 100g")).closest("tr")!;
    expect(within(parle).getByText("₹8.50")).toBeInTheDocument();
    expect(within(parle).getByText("18%")).toBeInTheDocument();
    const hidden = screen.getByText("Hide me").closest("tr")!;
    expect(within(hidden).getByText("Hidden from shops")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("combobox", { name: "Own brand" }));
    await userEvent.click(await screen.findByRole("option", { name: "Own brand only" }));
    await waitFor(() =>
      expect(calls.some((c) => c.url.searchParams.get("own_brand") === "true")).toBe(true),
    );
    await userEvent.type(screen.getByRole("searchbox", { name: "Search products" }), "parle");
    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.path === "/api/v1/products/" && c.url.searchParams.get("search") === "parle",
        ),
      ).toBe(true),
    );
  });

  it("applies bulk actions to the selected products", async () => {
    const calls = mockApi({
      ...masters,
      "/api/v1/products/": () => [
        200,
        { next: null, previous: null, results: [row("PG-100", "Parle-G 100g"), row("A", "Atta")] },
      ],
      "POST /api/v1/products/bulk/": () => [200, { changed: 2 }],
    });
    renderWithIntl(<ProductsPage />);
    await userEvent.click(
      await screen.findByRole("checkbox", { name: "Select all products on this page" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Hide from shops" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        product_ids: ["id-PG-100", "id-A"],
        action: "hide_from_shop",
        value: null,
      }),
    );
  });

  it("makes one supplier the preferred one for the selected products (purchasing on)", async () => {
    features.add("purchasing");
    permissions.add("purchasing.manage");
    const calls = mockApi({
      ...masters,
      "/api/v1/products/": () => [
        200,
        { next: null, previous: null, results: [row("PG-100", "Parle-G 100g"), row("A", "Atta")] },
      ],
      "/api/v1/suppliers/": () => [
        200,
        { next: null, previous: null, results: [{ id: "s1", name: "Hindustan Traders" }] },
      ],
      "POST /api/v1/suppliers/s1/products/": () => [200, { changed: 2 }],
    });
    renderWithIntl(<ProductsPage />);
    await userEvent.click(
      await screen.findByRole("checkbox", { name: "Select all products on this page" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Set preferred supplier" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Supplier" }));
    await userEvent.click(await screen.findByRole("option", { name: "Hindustan Traders" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/suppliers/s1/products/")?.body).toEqual({
        product_ids: ["id-PG-100", "id-A"],
      }),
    );
    features.delete("purchasing");
  });

  it("hides changes from people who can only view", async () => {
    permissions.delete("products.manage");
    mockApi({
      ...masters,
      "/api/v1/products/": () => [200, { next: null, previous: null, results: [row("A", "Atta")] }],
    });
    renderWithIntl(<ProductsPage />);
    await screen.findByText("Atta");
    expect(screen.queryByRole("link", { name: "Add product" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});

describe("Product editor", () => {
  it("sends decimals as the strings typed (commas removed) and shows server field errors", async () => {
    const calls = mockApi({
      ...masters,
      "POST /api/v1/products/": () => [
        400,
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "",
            details: { fields: { code: ["Another product already uses this code."] } },
          },
        },
      ],
    });
    renderWithIntl(<NewProductPage />);
    await userEvent.type(await screen.findByLabelText(/Product code/), "PG-100");
    await userEvent.type(screen.getByLabelText(/^Name/), "Parle-G");
    await userEvent.type(screen.getByLabelText(/^Price/), "1,234.50");
    await userEvent.type(screen.getByLabelText(/HSN code/), "1905");
    await userEvent.click(screen.getByRole("combobox", { name: /GST rate/ }));
    await userEvent.click(await screen.findByRole("option", { name: "18%" }));
    await userEvent.click(screen.getByRole("combobox", { name: /^Unit/ }));
    await userEvent.click(await screen.findByRole("option", { name: "PCS · Pieces" }));
    await userEvent.click(screen.getByRole("button", { name: "Add product" }));

    expect(await screen.findByText("Another product already uses this code.")).toBeInTheDocument();
    const body = calls.find((c) => c.method === "POST")?.body as Record<string, unknown>;
    expect(body).toMatchObject({
      code: "PG-100",
      base_price: "1234.50",
      gst_rate: "18.000",
      unit: "u-pcs",
      category: null,
      min_order_qty: "1",
    });
  });

  it("explains required fields before calling the server", async () => {
    const calls = mockApi(masters);
    renderWithIntl(<NewProductPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Add product" }));
    expect((await screen.findAllByText("This is required.")).length).toBeGreaterThan(2);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows server warnings, GST history and a missing current rate", async () => {
    const product: ProductDetail = {
      id: "p1",
      code: "PG-100",
      name: "Parle-G",
      description: "",
      category: null,
      brand: null,
      unit: { id: "u-pcs", code: "PCS", name: "Pieces", uqc: "NOS" },
      pack_unit: null,
      pack_size: null,
      hsn_code: "1905",
      mrp: "10.00",
      base_price: "10.00",
      cost_price: "6.00",
      own_brand: false,
      min_order_qty: "1.000",
      order_multiple: "1.000",
      reorder_level: "0.000",
      tags: [],
      show_in_shop: true,
      is_active: true,
      barcodes: [],
      images: [],
      current_rate: null,
      tax_rates: [
        {
          id: "r1",
          gst_rate: "5.000",
          cess_type: null,
          cess_rate: "0.000",
          effective_from: "2026-10-01",
          reason: "Budget",
          state: "SCHEDULED",
          cancelled_at: null,
          cancel_reason: "",
          created_at: "2026-09-25T10:00:00Z",
        },
      ],
      hsn_hint: null,
      warnings: [
        {
          code: "PRICE_ABOVE_MRP",
          message: "",
          details: { price_with_gst: "10.50", mrp: "10.00" },
        },
      ],
      created_at: "2026-09-25T10:00:00Z",
      updated_at: "2026-09-25T10:00:00Z",
    };
    mockApi({
      ...masters,
      "/api/v1/products/p1/": () => [200, product],
      "/api/v1/products/p1/images/": () => [200, []],
    });
    renderWithIntl(<EditProductPage productId="p1" />);
    expect(
      await screen.findByText(/The price including GST \(₹10.50\) is above the MRP \(₹10.00\)/),
    ).toBeInTheDocument();
    expect(screen.getByText(/no GST rate in effect today/)).toBeInTheDocument();
    expect(screen.getByText("Scheduled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel this change" })).toBeInTheDocument();
    expect(screen.getByLabelText("Cost price")).toHaveValue("6.00");
  });

  it("never shows the cost price field to staff without cost access", async () => {
    // Sales keep pricing.view for selling prices but never see costs (ADR-042).
    permissions.delete("costs.view");
    permissions.delete("costs.manage");
    const calls = mockApi({ ...masters, "POST /api/v1/products/": () => [201, { id: "p9" }] });
    renderWithIntl(<NewProductPage />);
    await screen.findByLabelText(/Product code/);
    expect(screen.queryByLabelText("Cost price")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Product code/), "X-1");
    await userEvent.type(screen.getByLabelText(/^Name/), "X");
    await userEvent.type(screen.getByLabelText(/^Price/), "5");
    await userEvent.type(screen.getByLabelText(/HSN code/), "1905");
    await userEvent.click(screen.getByRole("combobox", { name: /GST rate/ }));
    await userEvent.click(await screen.findByRole("option", { name: "5%" }));
    await userEvent.click(screen.getByRole("combobox", { name: /^Unit/ }));
    await userEvent.click(await screen.findByRole("option", { name: "PCS · Pieces" }));
    await userEvent.click(screen.getByRole("button", { name: "Add product" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).not.toHaveProperty("cost_price");
  });
});

describe("CategoriesPage", () => {
  it("shows the tree and only offers sub-categories down to level 3", async () => {
    mockApi(masters);
    renderWithIntl(<CategoriesPage />);
    expect(await screen.findByText("Biscuits")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a category under Food" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add a category under Biscuits" }),
    ).toBeInTheDocument();
  });
});
