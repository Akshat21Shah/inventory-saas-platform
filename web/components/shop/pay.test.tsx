import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Checkout } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { PayAccountCard, PayBillButton, ShopCheckoutPage } from "./pay";

const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("sonner", () => ({ toast }));
const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/shop/invoices/i1",
}));

afterEach(() => {
  vi.unstubAllGlobals();
  router.push.mockReset();
  toast.error.mockReset();
});

const checkout = (over: Partial<Checkout> = {}): Checkout => ({
  id: "c1",
  purpose: "INVOICE",
  invoice_id: "i1",
  invoice_number: "INV/26-27/000001",
  amount: "210.00",
  status: "CREATED",
  provider: "MOCK",
  checkout: { provider: "MOCK", checkout_url: "/api/v1/dev/mock-gateway/order_mock_1/" },
  expires_at: "2026-09-30T06:00:00Z",
  last_error: "",
  payment_id: null,
  receipt_number: "",
  created_at: "2026-09-30T05:30:00Z",
  paid_at: null,
  ...over,
});

const account = (online: boolean) => ({ online_payments: online, position: { owed: "210.00" } });

describe("Paying online", () => {
  it("offers Pay on a bill only while the distributor takes online payments", async () => {
    mockApi({ "/api/v1/shop/account/": () => [200, account(false)] });
    const { unmount } = renderWithIntl(<PayBillButton invoiceId="i1" balance="210.00" />);
    await waitFor(() => expect(screen.queryByRole("button")).toBeNull());
    unmount();
    mockApi({ "/api/v1/shop/account/": () => [200, account(true)] });
    renderWithIntl(<PayBillButton invoiceId="i1" balance="0.00" />);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("button")).toBeNull(); // nothing left to pay
  });

  it("starts the bill's checkout with an Idempotency-Key and opens it", async () => {
    const calls = mockApi({
      "/api/v1/shop/account/": () => [200, account(true)],
      "POST /api/v1/shop/payments/checkout/": () => [200, checkout()],
    });
    renderWithIntl(<PayBillButton invoiceId="i1" balance="210.00" />);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Pay ₹210.00" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/shop/payments/checkout/c1"));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ purpose: "INVOICE", invoice_id: "i1" });
    expect(post.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f]{32}$/);
  });

  it("says the payment service is busy, and stays on the page", async () => {
    mockApi({
      "/api/v1/shop/account/": () => [200, account(true)],
      "POST /api/v1/shop/payments/checkout/": () => [
        503,
        {
          error: {
            code: "PAYMENT_GATEWAY_UNAVAILABLE",
            message: "Payment service is busy, please try again in a minute.",
            details: {},
          },
        },
      ],
    });
    renderWithIntl(<PayBillButton invoiceId="i1" balance="210.00" />);
    const pay = await screen.findByRole("button", { name: "Pay ₹210.00" });
    await userEvent.setup().click(pay);
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Payment service is busy, please try again in a minute.",
      ),
    );
    expect(router.push).not.toHaveBeenCalled();
    expect(pay).toBeEnabled();
  });

  it("pays everything owed, or an amount the shop chooses", async () => {
    const calls = mockApi({
      "POST /api/v1/shop/payments/checkout/": () => [200, checkout({ purpose: "CUSTOM" })],
    });
    const user = userEvent.setup();
    const { unmount } = renderWithIntl(<PayAccountCard owed="210.00" online />);
    await user.click(screen.getByRole("button", { name: "Pay everything: ₹210.00" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledTimes(1));
    unmount(); // the page moves on to the checkout
    renderWithIntl(<PayAccountCard owed="210.00" online />);
    await user.type(screen.getByLabelText(/another amount/), "100");
    await user.click(screen.getByRole("button", { name: "Pay" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "POST").map((c) => c.body)).toEqual([
        { purpose: "OUTSTANDING" },
        { purpose: "CUSTOM", amount: "100" },
      ]),
    );
  });
});

describe("The checkout page", () => {
  it("opens the test gateway's page", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    mockApi({ "/api/v1/shop/payments/checkout/c1/": () => [200, checkout()] });
    renderWithIntl(<ShopCheckoutPage intentId="c1" />);
    expect(await screen.findByText("For bill INV/26-27/000001")).toBeVisible();
    await userEvent.setup().click(screen.getByRole("button", { name: "Pay ₹210.00 now" }));
    expect(assign).toHaveBeenCalledWith("/api/v1/dev/mock-gateway/order_mock_1/");
  });

  it("waits for the bank, then shows the receipt", async () => {
    mockApi({
      "/api/v1/shop/payments/checkout/c1/": () => [200, checkout({ status: "ATTEMPTED" })],
    });
    const { unmount } = renderWithIntl(<ShopCheckoutPage intentId="c1" />);
    expect(await screen.findByText(/Waiting for the bank to confirm/)).toBeVisible();
    unmount();
    mockApi({
      "/api/v1/shop/payments/checkout/c1/": () => [
        200,
        checkout({ status: "PAID", payment_id: "p1", receipt_number: "RCT/26-27/000007" }),
      ],
    });
    renderWithIntl(<ShopCheckoutPage intentId="c1" />);
    expect(await screen.findByText("Thank you. Receipt RCT/26-27/000007.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Download receipt" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /now$/ })).toBeNull();
  });

  it("starts again once a checkout expired", async () => {
    mockApi({
      "/api/v1/shop/payments/checkout/c1/": () => [200, checkout({ status: "EXPIRED" })],
    });
    renderWithIntl(<ShopCheckoutPage intentId="c1" />);
    expect(await screen.findByRole("link", { name: "Start again" })).toHaveAttribute(
      "href",
      "/shop/invoices/i1",
    );
  });
});
