import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import type { Quote } from "@/lib/api/generated/model";
import { mockApi, type ApiCall } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { CartPage } from "./cart";
import { CartProvider, useCart } from "./cart-state";
import { QuantityStepper } from "./quantity-stepper";

const auth = { me: { id: "u1", retailer: { shop_name: "Ganesh Kirana", on_hold: false } } };
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const router = { replace: vi.fn(), push: vi.fn(), back: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/shop/cart",
  useSearchParams: () => new URLSearchParams(),
}));

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  router.push.mockReset();
});

const renderShop = (ui: ReactElement) => renderWithIntl(<CartProvider>{ui}</CartProvider>);

const biscuit = {
  id: "p1",
  name: "Parle-G",
  min_order_qty: "6.000",
  order_multiple: "6.000",
  unit: { name: "pieces" },
};

function quote(lines: Array<{ id: string; qty: string; later?: string }>): Quote {
  return {
    lines: lines.map(({ id, qty, later = "0.000" }) => ({
      product_id: id,
      product: {
        id,
        code: id,
        name: id === "p1" ? "Parle-G" : "Tea",
        unit: { code: "PCS", name: "pieces", allows_decimal: false },
        pack_unit: null,
        pack_size: null,
        min_order_qty: "1.000",
        order_multiple: "1.000",
        thumbnail_url: null,
      },
      quantity: qty,
      unit_price: "10.00",
      discount_total: "0.00",
      discount_percent: "0.00",
      line_total: "63.00",
      ready_qty: later === "0.000" ? qty : "0.000",
      later_qty: later,
      stock: null,
      problems: [],
      is_free: false,
      free_of_product_id: null,
      scheme: null,
      offer: null,
    })),
    item_count: lines.length,
    totals: {
      gross: "60.00",
      discount: "0.00",
      taxable: "60.00",
      tax: "3.00",
      round_off: "0.00",
      grand_total: "63.00",
    },
    prices_include_gst: false,
    backorders_enabled: true,
    credit: { limit: null, available: null, outcome: "OK", reason: "" },
    problems: [],
    can_place: lines.length > 0,
    address_id: null,
    expected_total: "63.00",
  };
}

function CartCount() {
  const { count } = useCart();
  return <output aria-label="cart count">{count}</output>;
}

describe("Quick ordering", () => {
  it("adds the minimum, steps by the multiple, and sends only the last quantity", async () => {
    let cart = quote([]);
    const calls = mockApi({
      "/api/v1/shop/cart/": () => [200, cart],
      "PUT /api/v1/shop/cart/lines/p1/": (body) => {
        cart = quote([{ id: "p1", qty: (body as { quantity: string }).quantity }]);
        return [200, cart];
      },
    });
    const user = userEvent.setup();
    renderShop(
      <>
        <QuantityStepper product={biscuit} />
        <CartCount />
      </>,
    );
    await user.click(await screen.findByRole("button", { name: "Add Parle-G to cart" }));
    expect(screen.getByRole("textbox", { name: "Quantity of Parle-G" })).toHaveValue("6");
    await user.click(screen.getByRole("button", { name: "More Parle-G" }));
    await user.click(screen.getByRole("button", { name: "More Parle-G" }));
    expect(screen.getByRole("textbox", { name: "Quantity of Parle-G" })).toHaveValue("18");
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ quantity: "18" });
    await waitFor(() => expect(screen.getByLabelText("cart count")).toHaveTextContent("1"));
    await user.click(screen.getByRole("button", { name: "Fewer Parle-G" }));
    await user.click(screen.getByRole("button", { name: "Fewer Parle-G" }));
    await user.click(screen.getByRole("button", { name: "Fewer Parle-G" }));
    expect(screen.getByRole("button", { name: "Add Parle-G to cart" })).toBeVisible();
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "PUT").at(-1)!.body).toEqual({ quantity: "0" }),
    );
  });
});

/** Make the next POST to /shop/orders/ fail as if the connection dropped (after the server
 * may or may not have placed the order). */
function dropNextPlacement(calls: ApiCall[]) {
  const through = globalThis.fetch as Mock;
  let dropped = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      if (!dropped && init.method === "POST" && String(input).endsWith("/api/v1/shop/orders/")) {
        dropped = true;
        calls.push({
          method: "POST",
          path: "/api/v1/shop/orders/",
          url: new URL(input, "http://localhost"),
          body: JSON.parse(String(init.body)),
          headers: new Headers(init.headers),
        });
        throw new TypeError("Failed to fetch");
      }
      return through(input, init);
    }),
  );
}

describe("Checkout on a poor connection", () => {
  it("places with an Idempotency-Key and opens the order", async () => {
    const calls = mockApi({
      "/api/v1/shop/cart/": () => [200, quote([{ id: "p1", qty: "6.000" }])],
      "/api/v1/shop/addresses/": () => [200, []],
      "POST /api/v1/shop/orders/": () => [201, { id: "o1" }],
    });
    const user = userEvent.setup();
    renderShop(<CartPage />);
    await user.click(await screen.findByRole("button", { name: /Place order · ₹63.00/ }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/shop/orders/o1?placed=1"));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f]{32}$/);
    expect(post.body).toEqual({ expected_total: "63.00", address: null, note: "" });
  });

  it("after a dropped connection, checks first and retries with the same key", async () => {
    const calls = mockApi({
      "/api/v1/shop/cart/": () => [200, quote([{ id: "p1", qty: "6.000" }])],
      "/api/v1/shop/addresses/": () => [200, []],
      "POST /api/v1/shop/orders/": () => [201, { id: "o1" }],
    });
    const checked: string[] = [];
    const routes = globalThis.fetch as Mock;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        const match = /\/checkout-attempts\/([^/]+)\//.exec(String(input));
        if (match) {
          checked.push(match[1] ?? "");
          return new Response(JSON.stringify({ status: "not_found", order: null, number: null }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        return routes(input, init);
      }),
    );
    dropNextPlacement(calls);
    const user = userEvent.setup();
    renderShop(<CartPage />);
    await user.click(await screen.findByRole("button", { name: /Place order/ }));
    expect(await screen.findByText(/The connection dropped/)).toBeVisible();
    expect(router.push).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/shop/orders/o1?placed=1"));
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts).toHaveLength(2);
    const [first, second] = posts;
    const key = first!.headers.get("Idempotency-Key");
    expect(second!.headers.get("Idempotency-Key")).toBe(key);
    expect(checked).toEqual([key]);
  });

  it("when the dropped attempt went through, opens that order without posting again", async () => {
    const calls = mockApi({
      "/api/v1/shop/cart/": () => [200, quote([{ id: "p1", qty: "6.000" }])],
      "/api/v1/shop/addresses/": () => [200, []],
    });
    const routes = globalThis.fetch as Mock;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) =>
        String(input).includes("/checkout-attempts/")
          ? new Response(JSON.stringify({ status: "placed", order: "o9", number: "ORD-9" }), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            })
          : routes(input, init),
      ),
    );
    dropNextPlacement(calls);
    const user = userEvent.setup();
    renderShop(<CartPage />);
    await user.click(await screen.findByRole("button", { name: /Place order/ }));
    await user.click(await screen.findByRole("button", { name: "Try again" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/shop/orders/o9?placed=1"));
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
  });

  it("after a reload, finds an attempt that went through", async () => {
    window.localStorage.setItem(
      "shop.checkout-attempt:u1",
      JSON.stringify({ key: "abcdef0123456789", cart: "x", startedAt: 1 }),
    );
    mockApi({
      "/api/v1/shop/cart/": () => [200, quote([{ id: "p1", qty: "6.000" }])],
      "/api/v1/shop/addresses/": () => [200, []],
      "/api/v1/shop/checkout-attempts/abcdef0123456789/": () => [
        200,
        { status: "placed", order: "o7", number: "ORD-7" },
      ],
    });
    renderShop(<CartPage />);
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/shop/orders/o7?placed=1"));
    expect(window.localStorage.getItem("shop.checkout-attempt:u1")).toBeNull();
  });

  it("shows what comes later and a price change in plain words", async () => {
    mockApi({
      "/api/v1/shop/cart/": () => [
        200,
        quote([
          { id: "p1", qty: "6.000" },
          { id: "p2", qty: "4.000", later: "4.000" },
        ]),
      ],
      "/api/v1/shop/addresses/": () => [200, []],
      "POST /api/v1/shop/orders/": () => [
        409,
        { error: { code: "PRICE_CHANGED", message: "", details: {} } },
      ],
    });
    const user = userEvent.setup();
    renderShop(<CartPage />);
    expect(await screen.findByRole("heading", { name: "Comes later" })).toBeVisible();
    expect(screen.getByText("Comes later, when stock arrives")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /Place order/ }));
    expect(await screen.findByText(/prices changed/i)).toBeVisible();
  });

  it("shows free goods as their own line, and what to add for more", async () => {
    const base = quote([{ id: "p1", qty: "12.000" }]);
    const terms = {
      scheme_id: "s1",
      name: "Diwali offer",
      buy_qty: "10.000",
      free_qty: "1.000",
      repeat: true,
      max_free_qty: null,
      same_product: true,
      free_product_name: "Parle-G",
      free_unit: "PCS",
    };
    const paid = base.lines[0]!;
    const cart: Quote = {
      ...base,
      lines: [
        { ...paid, scheme: terms, offer: { scheme: terms, add_qty: "8.000", free_qty: "1.000" } },
        {
          ...paid,
          quantity: "1.000",
          unit_price: "0.00",
          line_total: "0.00",
          is_free: true,
          free_of_product_id: "p1",
          scheme: terms,
          offer: null,
        },
      ],
    };
    mockApi({
      "/api/v1/shop/cart/": () => [200, cart],
      "/api/v1/shop/addresses/": () => [200, []],
    });
    renderShop(
      <>
        <CartPage />
        <CartCount />
      </>,
    );
    expect(await screen.findByText("Add 8 more to get 1 free")).toBeVisible();
    expect(screen.getByText("with Diwali offer")).toBeVisible();
    expect(screen.getByText("1 free")).toBeVisible();
    // One stepper (the bought line), and the free line doesn't change the count.
    expect(screen.getAllByRole("textbox", { name: "Quantity of Parle-G" })).toHaveLength(1);
    expect(screen.getByRole("textbox", { name: "Quantity of Parle-G" })).toHaveValue("12");
    expect(screen.getByLabelText("cart count")).toHaveTextContent("1");
  });

  it("says why an order waits for approval, or can't be placed, when bills are overdue", async () => {
    const waiting: Quote = {
      ...quote([{ id: "p1", qty: "6.000" }]),
      credit: { limit: null, available: null, outcome: "NEEDS_APPROVAL", reason: "OVERDUE" },
      problems: [
        { code: "CREDIT_APPROVAL_NEEDED", details: { reason: "OVERDUE" }, blocking: false },
      ],
    };
    const blocked: Quote = {
      ...waiting,
      credit: { ...waiting.credit, outcome: "BLOCKED" },
      problems: [
        { code: "OVERDUE_INVOICES", details: { oldest_due: "2026-08-01" }, blocking: true },
      ],
      can_place: false,
    };
    let current = waiting;
    mockApi({
      "/api/v1/shop/cart/": () => [200, current],
      "/api/v1/shop/addresses/": () => [200, []],
    });
    const first = renderShop(<CartPage />);
    expect(
      await screen.findByText(/You have overdue bills. Your distributor will approve/),
    ).toBeVisible();
    first.unmount();
    current = blocked;
    renderShop(<CartPage />);
    expect(await screen.findByText(/You have overdue bills. Please pay them/)).toBeVisible();
    expect(screen.getByRole("button", { name: /Place order/ })).toBeDisabled();
  });
});
