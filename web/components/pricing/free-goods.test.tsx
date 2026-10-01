import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FreeGoodsScheme } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";
import { setViewport } from "@/tests/viewport";

import { FreeGoodsPage, NewFreeGoodsPage } from "./free-goods";

let modules = new Set(["free_goods"]);
const auth = {
  me: { id: "u1" },
  can: () => true,
  feature: (code: string) => modules.has(code),
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/manage/pricing/free-goods",
  useSearchParams: () => new URLSearchParams(),
}));

beforeEach(() => {
  modules = new Set(["free_goods"]);
  router.push.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

const product = (id: string, name: string) => ({ id, code: id.toUpperCase(), name });
const scheme = (extra: Partial<FreeGoodsScheme> = {}): FreeGoodsScheme => ({
  id: "s1",
  name: "Rice 12 + 1",
  buy_product: product("p1", "Sona Masoori 1kg"),
  buy_unit: "PCS",
  buy_qty: "12.000",
  free_product: product("p1", "Sona Masoori 1kg"),
  free_unit: "PCS",
  free_qty: "1.000",
  repeat: true,
  max_free_qty: null,
  audience_type: "ALL",
  price_list: null,
  retailer: null,
  valid_from: null,
  valid_to: null,
  is_active: true,
  created_at: "2026-10-01T10:00:00Z",
  updated_at: "2026-10-01T10:00:00Z",
  ...extra,
});
const page = (results: unknown[]) =>
  [200, { next: null, previous: null, results }] as [number, unknown];

describe("FreeGoodsPage", () => {
  it("lists the offers in plain words", async () => {
    mockApi({
      "/api/v1/free-goods-schemes/": () =>
        page([
          scheme(),
          scheme({
            id: "s2",
            name: "Shampoo with cleaner",
            buy_product: product("p2", "Herbal Shampoo"),
            buy_qty: "6.000",
            free_product: product("p3", "Floor Cleaner"),
            max_free_qty: "5.000",
            audience_type: "RETAILER",
            retailer: { id: "r1", code: "R-1", shop_name: "Ganesh Kirana" },
          }),
        ]),
    });
    renderWithIntl(<FreeGoodsPage />);
    const rice = (await screen.findByText("Rice 12 + 1")).closest("tr")!;
    expect(within(rice).getByText("Buy 12, get 1 free")).toBeInTheDocument();
    expect(within(rice).getByText("All shops")).toBeInTheDocument();
    const shampoo = screen.getByText("Shampoo with cleaner").closest("tr")!;
    expect(within(shampoo).getByText("Buy 6, get 1 Floor Cleaner free")).toBeInTheDocument();
    expect(within(shampoo).getByText("For every lot bought · at most 5 free")).toBeInTheDocument();
    expect(within(shampoo).getByText("Ganesh Kirana")).toBeInTheDocument();
  });

  it("shows cards on a phone", async () => {
    setViewport(360);
    mockApi({ "/api/v1/free-goods-schemes/": () => page([scheme()]) });
    renderWithIntl(<FreeGoodsPage />);
    await screen.findByText("Rice 12 + 1");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says when the module is off", () => {
    modules = new Set();
    renderWithIntl(<FreeGoodsPage />);
    expect(screen.getByText("Free goods are switched off")).toBeInTheDocument();
  });
});

describe("NewFreeGoodsPage", () => {
  it("sends the offer as typed", async () => {
    const calls = mockApi({
      "/api/v1/price-lists/": () => page([]),
      "/api/v1/products/search/": () => [
        200,
        [{ ...product("p1", "Sona Masoori 1kg"), unit: "PCS" }],
      ],
      "POST /api/v1/free-goods-schemes/": () => [201, scheme()],
    });
    renderWithIntl(<NewFreeGoodsPage />);
    await userEvent.type(await screen.findByLabelText(/^Name/), "Rice 12 + 1");
    await userEvent.type(screen.getByRole("combobox", { name: /Product bought/ }), "sona");
    await userEvent.click(await screen.findByRole("option", { name: /Sona Masoori/ }));
    await userEvent.type(screen.getByLabelText(/Quantity to buy/), "12");
    await userEvent.type(screen.getByLabelText(/Most free on one order/), "3");
    await userEvent.click(screen.getByRole("button", { name: "Add the offer" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/manage/pricing/free-goods"));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      name: "Rice 12 + 1",
      buy_product: "p1",
      buy_qty: "12",
      free_product: "p1",
      free_qty: "1",
      repeat: true,
      max_free_qty: "3",
      audience_type: "ALL",
    });
  });
});
