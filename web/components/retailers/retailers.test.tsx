import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RetailerDetail, RetailerList } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { NewRetailerPage, RetailerDetailPage } from "./retailer-editor";
import { RetailersPage } from "./retailers-page";

const permissions = new Set([
  "retailers.view",
  "retailers.manage",
  "pricing.view",
  "pricing.manage",
  "credit.manage",
]);
const auth = {
  me: { id: "u1" },
  can: (p: string) => permissions.has(p),
  feature: () => false,
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/manage",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  permissions.add("credit.manage");
});

const shop = (id: string, name: string, extra: Partial<RetailerList> = {}): RetailerList => ({
  id,
  code: `R-0000${id}`,
  shop_name: name,
  owner_name: "Ganesh",
  mobile: "+919876500001",
  gstin: null,
  state_code: "27",
  status: "ACTIVE",
  salesperson: null,
  price_list: null,
  credit_limit: "50000.00",
  payment_terms_days: 15,
  tags: [],
  ...extra,
});

const options = {
  "/api/v1/price-lists/": () =>
    [200, { next: null, previous: null, results: [{ id: "pl-gold", name: "Gold" }] }] as [
      number,
      unknown,
    ],
  "/api/v1/retailers/salespeople/": () =>
    [200, [{ id: "s1", full_name: "Ravi", email: "ravi@example.com" }]] as [number, unknown],
  "/api/v1/public/states/": () => [200, [{ code: "27", name: "Maharashtra" }]] as [number, unknown],
};

describe("RetailersPage", () => {
  it("lists shops with their price list and status, and assigns a price list in bulk", async () => {
    const calls = mockApi({
      ...options,
      "/api/v1/retailers/": () => [
        200,
        {
          next: null,
          previous: null,
          results: [
            shop("1", "Ganesh Kirana", { price_list: { id: "pl-gold", name: "Gold" } }),
            shop("2", "Laxmi Stores", { status: "BLOCKED" }),
          ],
        },
      ],
      "POST /api/v1/retailers/bulk/": () => [200, { changed: 1 }],
    });
    renderWithIntl(<RetailersPage />);
    const ganesh = (await screen.findByText("Ganesh Kirana")).closest("tr")!;
    expect(within(ganesh).getByText("Gold")).toBeInTheDocument();
    expect(within(ganesh).getByText("+91 98765 00001")).toBeInTheDocument();
    const laxmi = screen.getByText("Laxmi Stores").closest("tr")!;
    expect(within(laxmi).getByText("On hold")).toBeInTheDocument();
    expect(within(laxmi).getByText("Standard prices")).toBeInTheDocument();

    await userEvent.click(within(laxmi).getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Assign price list" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("combobox", { name: /Price list/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Gold" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        retailer_ids: ["2"],
        action: "assign_price_list",
        value: "pl-gold",
      }),
    );
  });
});

describe("Retailer form", () => {
  it("creates a shop with its billing address and shows the server's GSTIN error", async () => {
    const calls = mockApi({
      ...options,
      "POST /api/v1/retailers/": () => [
        400,
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "",
            details: { fields: { gstin: ["The last character of this GSTIN is wrong."] } },
          },
        },
      ],
    });
    renderWithIntl(<NewRetailerPage />);
    await userEvent.type(await screen.findByLabelText(/Shop name/), "Ganesh Kirana");
    await userEvent.type(screen.getByLabelText(/Mobile number/), "98765 00001");
    await userEvent.type(screen.getByLabelText(/GSTIN/), "27aapfu0939f1zv");
    await userEvent.type(screen.getByLabelText(/Address line 1/), "Shop 4, Market Road");
    await userEvent.type(screen.getByLabelText(/City or town/), "Pune");
    await userEvent.type(screen.getByLabelText(/PIN code/), "411001");
    await userEvent.click(screen.getByRole("button", { name: "Add retailer" }));
    expect(await screen.findByText("The last character of this GSTIN is wrong.")).toBeVisible();
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      shop_name: "Ganesh Kirana",
      mobile: "9876500001",
      gstin: "27AAPFU0939F1ZV",
      price_list: null,
      billing_address: { line1: "Shop 4, Market Road", city: "Pune", pincode: "411001" },
    });
  });

  it("shows the shop's server-worked prices and hides credit changes without permission", async () => {
    permissions.delete("credit.manage");
    const retailer: RetailerDetail = {
      ...shop("1", "Ganesh Kirana"),
      email: "",
      pan: "",
      blocked_reason: "",
      notes: "",
      preferred_language: "",
      language: "en",
      welcome_sent_at: null,
      addresses: [],
      created_at: "2026-09-25T10:00:00Z",
      updated_at: "2026-09-25T10:00:00Z",
    };
    mockApi({
      ...options,
      "/api/v1/retailers/1/": () => [200, retailer],
      "/api/v1/retailers/1/prices/": () => [
        200,
        {
          next: null,
          previous: null,
          results: [
            {
              product: { id: "p1", code: "PG-100", name: "Parle-G" },
              result: {
                product_id: "p1",
                qty: "12.000",
                base_price: "10.00",
                unit_price: "9.00",
                price_source: "PRICE_LIST",
                discounts: [
                  {
                    rule_id: "d1",
                    rule_name: "Bulk",
                    discount_type: "PERCENT",
                    value: "5.00",
                    slab_min_qty: "12.000",
                    amount: "5.40",
                  },
                ],
                discount_total: "5.40",
                discount_percent: "5.00",
                gross: "108.00",
                line_net: "102.60",
                net_unit_price: "8.55",
                gst_rate: "5.000",
                cess_rate: "0.000",
                prices_include_gst: false,
                on: "2026-09-25",
              },
            },
          ],
        },
      ],
    });
    renderWithIntl(<RetailerDetailPage retailerId="1" />);
    const row = (await screen.findByText("Parle-G")).closest("tr")!;
    expect(within(row).getByText("₹9.00")).toBeInTheDocument();
    expect(within(row).getByText("Price list")).toBeInTheDocument();
    expect(within(row).getByText("₹8.55")).toBeInTheDocument();
    expect(within(row).getByText("Bulk")).toBeInTheDocument();
    expect(screen.getByText("₹50,000.00")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change" })).not.toBeInTheDocument();
  });
});
