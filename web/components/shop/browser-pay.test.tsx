import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PayCheckout } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { BrowserPayPage } from "./browser-pay";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const checkout = (over: Partial<PayCheckout> = {}): PayCheckout => ({
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
  awaiting_confirmation: false,
  page_open: true,
  app_return_url: "shopapp://shop/payments/checkout/c1",
  ...over,
});

const assign = vi.fn();

beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal("location", { ...window.location, assign, hash: "", pathname: "/pay/c1" });
});

afterEach(() => {
  vi.unstubAllGlobals();
  assign.mockReset();
});

describe("The app's browser payment page", () => {
  it("opens with the link's code, keeps the session to this tab, and pays this checkout", async () => {
    window.location.hash = "#code=one-time";
    const calls = mockApi({
      "POST /api/v1/pay/session/": () => [
        200,
        { token: "tok", expires_at: "2026-09-30T06:00:00Z", checkout: checkout() },
      ],
      "/api/v1/pay/checkout/": () => [200, checkout()],
    });
    renderWithIntl(<BrowserPayPage intentId="c1" />);
    expect(await screen.findByRole("heading", { name: "₹210.00" })).toBeInTheDocument();
    expect(calls[0]!.body).toEqual({ code: "one-time" });
    expect(sessionStorage.getItem("pay:c1")).toBe("tok");
    const read = calls.find((c) => c.path.endsWith("/pay/checkout/"))!;
    expect(read.headers.get("Authorization")).toBe("Pay tok"); // never a shop session
    // No shop menus: only paying and going back to the app.
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.getByRole("link", { name: "Back to the app" })).toHaveAttribute(
      "href",
      "shopapp://shop/payments/checkout/c1",
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Pay ₹210.00 now" }));
    expect(assign).toHaveBeenCalledWith("/api/v1/dev/mock-gateway/order_mock_1/?back=pay");
  });

  it("comes back from the gateway with the session this tab kept", async () => {
    sessionStorage.setItem("pay:c1", "kept");
    const calls = mockApi({ "/api/v1/pay/checkout/": () => [200, checkout()] });
    renderWithIntl(<BrowserPayPage intentId="c1" />);
    await screen.findByRole("heading", { name: "₹210.00" });
    expect(calls.every((c) => !c.path.endsWith("/pay/session/"))).toBe(true);
    expect(calls[0]!.headers.get("Authorization")).toBe("Pay kept");
  });

  it("when paid, says so and goes back to the app", async () => {
    sessionStorage.setItem("pay:c1", "kept");
    mockApi({
      "/api/v1/pay/checkout/": () => [
        200,
        checkout({ status: "PAID", page_open: false, receipt_number: "RCT/26-27/000001" }),
      ],
    });
    renderWithIntl(<BrowserPayPage intentId="c1" />);
    expect(await screen.findByRole("status")).toHaveTextContent("RCT/26-27/000001");
    await waitFor(
      () => expect(assign).toHaveBeenCalledWith("shopapp://shop/payments/checkout/c1"),
      {
        timeout: 3000,
      },
    );
  });

  it("says the page has closed when there's no session", async () => {
    mockApi({});
    renderWithIntl(<BrowserPayPage intentId="c1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This payment page has closed. Go back to the app to pay.",
    );
  });
});
