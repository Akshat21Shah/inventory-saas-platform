import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GridRow, RetailerDetail } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { RetailerDetailPage } from "../retailers/retailer-editor";
import { CopyPricingDialog } from "./copy-pricing";
import { DiscountGridPage } from "./discount-grid";

const permissions = new Set(["pricing.view", "pricing.manage", "retailers.view"]);
const auth = { me: { id: "u1" }, can: (p: string) => permissions.has(p) };
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/manage",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  permissions.add("pricing.manage");
});

const empty = { next: null, previous: null, results: [] };
const price = (unit: string, net: string, total = "0.00", percent = "0.00") => ({
  qty: "1.000",
  unit_price: unit,
  price_source: "BASE",
  discounts: [],
  discount_total: total,
  discount_percent: percent,
  net_unit_price: net,
});
const gridRow = (id: string, name: string, extra: Partial<GridRow> = {}): GridRow => ({
  product: { id, code: id.toUpperCase(), name },
  brand: null,
  category: null,
  simple: null,
  others: [],
  price: price("20.00", "20.00"),
  ...extra,
});
const shop = {
  id: "r1",
  code: "R-00001",
  shop_name: "Ganesh Kirana",
  owner_name: "",
  mobile: "+919876500001",
  email: "",
  gstin: null,
  pan: "",
  state_code: "27",
  status: "ACTIVE",
  blocked_reason: "",
  salesperson: null,
  price_list: null,
  credit_limit: null,
  payment_terms_days: 15,
  notes: "",
  tags: [],
  preferred_language: "en",
  welcome_sent_at: null,
  addresses: [],
  created_at: "2026-09-26T10:00:00Z",
  updated_at: "2026-09-26T10:00:00Z",
} satisfies RetailerDetail;
const lookups = {
  "/api/v1/categories/tree/": () => [200, []] as [number, unknown],
  "/api/v1/brands/": () => [200, empty] as [number, unknown],
  "/api/v1/retailers/r1/": () => [200, shop] as [number, unknown],
};

describe("Discount grid", () => {
  it("previews the net price from the server as you type, then saves the changes", async () => {
    const calls = mockApi({
      ...lookups,
      "/api/v1/retailers/r1/discount-grid/": () => [
        200,
        {
          ...empty,
          results: [
            gridRow("p1", "Parle-G"),
            gridRow("p2", "Monaco", {
              simple: {
                id: "d1",
                name: "R-00001 · P2",
                discount_type: "PERCENT",
                value: "5.00",
                is_active: true,
              },
              others: [
                {
                  id: "d9",
                  name: "Diwali slabs",
                  discount_type: "PERCENT",
                  value: "0.00",
                  is_active: true,
                },
              ],
              price: price("20.00", "19.00", "1.00", "5.00"),
            }),
          ],
        },
      ],
      "POST /api/v1/retailers/r1/discount-grid/preview/": () => [
        200,
        [
          {
            product: { id: "p1", code: "P1", name: "Parle-G" },
            price: price("20.00", "18.00", "2.00", "10.00"),
          },
        ],
      ],
      "PUT /api/v1/retailers/r1/discount-grid/": () => [200, { changed: 1, warnings: [] }],
    });
    renderWithIntl(<DiscountGridPage retailerId="r1" />);
    const monaco = (await screen.findByText("Monaco")).closest("tr")!;
    expect(within(monaco).getByRole("textbox", { name: "Discount for Monaco" })).toHaveValue(
      "5.00",
    );
    expect(within(monaco).getByText("5% off")).toBeVisible();
    expect(within(monaco).getByRole("link", { name: "Also: Diwali slabs" })).toHaveAttribute(
      "href",
      "/manage/pricing/discounts/d9",
    );

    await userEvent.type(screen.getByRole("textbox", { name: "Discount for Parle-G" }), "10");
    const parle = screen.getByText("Parle-G").closest("tr")!;
    await waitFor(() => expect(within(parle).getByText("₹18.00")).toBeVisible());
    const preview = calls.find((c) => c.path.endsWith("/preview/"));
    expect(preview?.body).toEqual({
      items: [{ product: "p1", discount_type: "PERCENT", value: "10" }],
    });

    await userEvent.click(screen.getByRole("button", { name: "Save 1 change" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      items: [{ product: "p1", discount_type: "PERCENT", value: "10" }],
    });
  });

  it("is read-only without pricing.manage", async () => {
    permissions.delete("pricing.manage");
    mockApi({
      ...lookups,
      "/api/v1/retailers/r1/discount-grid/": () => [
        200,
        { ...empty, results: [gridRow("p1", "Parle-G")] },
      ],
    });
    renderWithIntl(<DiscountGridPage retailerId="r1" />);
    expect(await screen.findByRole("textbox", { name: "Discount for Parle-G" })).toBeDisabled();
  });
});

describe("Copy pricing", () => {
  it("needs a shop and an explicit choice, previews, then copies with the previewed count", async () => {
    const plan = {
      price_list_from: null,
      price_list_to: "Gold",
      price_list_changes: true,
      prices_add: [{ code: "PG-100", name: "Parle-G", old: null, new: "8.00" }],
      prices_update: [],
      prices_remove: [],
      rules_add: ["R-00001 · PG-100"],
      rules_replace: [],
      rules_remove: [],
      changes: 3,
    };
    const calls = mockApi({
      "/api/v1/retailers/": () => [
        200,
        { ...empty, results: [{ id: "r2", code: "R-00002", shop_name: "Laxmi Stores" }] },
      ],
      "POST /api/v1/retailers/r1/copy-pricing/preview/": () => [200, plan],
      "POST /api/v1/retailers/r1/copy-pricing/": () => [200, plan],
    });
    const copied = vi.fn();
    renderWithIntl(<CopyPricingDialog retailerId="r1" shopName="Ganesh" onCopied={copied} />);
    await userEvent.click(screen.getByRole("button", { name: "Copy pricing from another shop" }));
    const dialog = await screen.findByRole("dialog");
    const previewButton = within(dialog).getByRole("button", { name: "Preview" });
    expect(previewButton).toBeDisabled();
    expect(within(dialog).getByRole("radio", { name: /^Replace/ })).not.toBeChecked();
    expect(within(dialog).getByRole("radio", { name: /^Add/ })).not.toBeChecked();
    await userEvent.type(within(dialog).getByRole("combobox", { name: /Copy from/ }), "lax");
    await userEvent.click(await within(dialog).findByRole("option", { name: /Laxmi Stores/ }));
    expect(previewButton).toBeDisabled(); // still no mode
    await userEvent.click(within(dialog).getByRole("radio", { name: /^Replace/ }));
    await userEvent.click(previewButton);
    expect(await within(dialog).findByText("Price list: standard prices → Gold")).toBeVisible();
    await userEvent.click(within(dialog).getByRole("button", { name: "Copy 3 changes" }));
    await waitFor(() => expect(copied).toHaveBeenCalled());
    expect(calls.find((c) => c.path === "/api/v1/retailers/r1/copy-pricing/")?.body).toEqual({
      copy_from: "r2",
      mode: "REPLACE",
      expected_changes: 3,
    });
  });
});

describe("Special prices on the retailer page", () => {
  it("edits a shop's special price in place and removes it when cleared", async () => {
    const calls = mockApi({
      ...lookups,
      "/api/v1/retailers/salespeople/": () => [200, []],
      "/api/v1/public/states/": () => [200, []],
      "/api/v1/price-lists/": () => [200, empty],
      "/api/v1/retailers/r1/prices/": () => [
        200,
        {
          ...empty,
          results: [
            {
              product: { id: "p1", code: "PG-100", name: "Parle-G" },
              result: {
                ...price("8.00", "8.00"),
                product_id: "p1",
                price_source: "SPECIAL",
                base_price: "10.00",
                gross: "8.00",
                line_net: "8.00",
                gst_rate: "5.000",
                cess_rate: "0.000",
                prices_include_gst: false,
                on: "2026-09-26",
              },
              special: { id: "sp1", price: "8.00" },
            },
            {
              product: { id: "p2", code: "MG-70", name: "Maggi" },
              result: {
                ...price("12.50", "12.50"),
                product_id: "p2",
                base_price: "12.50",
                gross: "12.50",
                line_net: "12.50",
                gst_rate: "5.000",
                cess_rate: "0.000",
                prices_include_gst: false,
                on: "2026-09-26",
              },
              special: null,
            },
          ],
        },
      ],
      "POST /api/v1/retailer-prices/": () => [201, { warnings: [] }],
      "DELETE /api/v1/retailer-prices/sp1/": () => [204, undefined],
    });
    renderWithIntl(<RetailerDetailPage retailerId="r1" />);
    const maggi = await screen.findByRole("textbox", { name: "Special price of Maggi" });
    await userEvent.type(maggi, "11.75");
    await userEvent.click(within(maggi.closest("form")!).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        retailer: "r1",
        product: "p2",
        price: "11.75",
      }),
    );
    const parle = screen.getByRole("textbox", { name: "Special price of Parle-G" });
    await userEvent.clear(parle);
    await userEvent.click(within(parle.closest("form")!).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(screen.getByRole("link", { name: "Add a discount for this shop" })).toHaveAttribute(
      "href",
      "/manage/pricing/discounts/new?retailer=r1",
    );
  });
});
