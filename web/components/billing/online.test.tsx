import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GatewaySettings, PaymentIntentRow } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { CheckoutsPage, GatewaySettingsPage } from "./online";

const features = new Set<string>();
const permissions = new Set<string>(["settings.manage", "payments.view"]);
const auth = {
  me: { id: "u1", tenant: { id: "t1" } },
  can: (p: string) => permissions.has(p),
  feature: (f: string) => features.has(f),
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/manage/payments/online",
}));

afterEach(() => {
  vi.unstubAllGlobals();
  features.clear();
});

const WEBHOOK = "http://sharma.localhost:3000/api/v1/webhooks/payments/razorpay/tok123/";
const gateway = (over: Partial<GatewaySettings> = {}): GatewaySettings => ({
  providers: ["RAZORPAY", "MOCK"],
  provider: "RAZORPAY",
  mode: "TEST",
  live_allowed: false,
  saved: { key_id: "••••AbCd", key_secret: "••••wxyz", webhook_secret: "••••1234" },
  status: "VERIFIED",
  verified_at: "2026-09-30T05:00:00Z",
  last_error: "",
  webhook_url: WEBHOOK,
  ...over,
});

describe("Online payments settings", () => {
  it("says online payments are off, asking nothing", async () => {
    const calls = mockApi({});
    renderWithIntl(<GatewaySettingsPage />);
    expect(await screen.findByText("Online payments aren't switched on")).toBeVisible();
    expect(calls).toEqual([]);
  });

  it("saves only the keys typed, never shows them back, and gives the webhook address", async () => {
    features.add("payments");
    const user = userEvent.setup();
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const calls = mockApi({
      "/api/v1/settings/payment-gateway/": () => [200, gateway()],
      "PUT /api/v1/settings/payment-gateway/": () => [200, gateway({ status: "CHECKING" })],
    });
    renderWithIntl(<GatewaySettingsPage />);
    expect(await screen.findByText("Working")).toBeVisible();
    expect(screen.getByText("Saved: ••••wxyz. Leave blank to keep it.")).toBeVisible();
    expect(screen.getByLabelText(/^Key secret/)).toHaveValue("");
    expect(screen.getByText("Only test keys can be used on this site.")).toBeVisible();
    expect(screen.getByText(WEBHOOK)).toBeVisible();
    expect(screen.getByText(/payment.captured and payment.failed/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith(WEBHOOK);
    await user.type(screen.getByLabelText(/^Key ID/), "  rzp_test_NEW  ");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        provider: "RAZORPAY",
        mode: "TEST",
        key_id: "rzp_test_NEW",
      }),
    );
  });

  it("shows the gateway's reason when the keys don't work", async () => {
    features.add("payments");
    mockApi({
      "/api/v1/settings/payment-gateway/": () => [
        200,
        gateway({ status: "FAILED", last_error: "Authentication failed" }),
      ],
    });
    renderWithIntl(<GatewaySettingsPage />);
    expect(await screen.findByText("The gateway said: Authentication failed")).toBeVisible();
    expect(screen.getByText("Not working")).toBeVisible();
  });
});

describe("Online checkouts", () => {
  const row: PaymentIntentRow = {
    id: "c1",
    purpose: "INVOICE",
    invoice_id: "i1",
    invoice_number: "INV/26-27/000001",
    amount: "210.00",
    status: "PAID",
    provider: "RAZORPAY",
    checkout: null,
    expires_at: "2026-09-30T06:00:00Z",
    last_error: "",
    payment_id: "p1",
    receipt_number: "RCT/26-27/000007",
    created_at: "2026-09-30T05:30:00Z",
    paid_at: "2026-09-30T05:31:00Z",
    shop_name: "Ganesh Kirana",
    retailer_id: "r1",
    client_outcome: "success",
  };

  it("lists what shops started paying, with the receipt once paid", async () => {
    features.add("payments");
    const calls = mockApi({
      "/api/v1/payment-intents/": () => [200, { next: null, previous: null, results: [row] }],
    });
    renderWithIntl(<CheckoutsPage />);
    const receipts = await screen.findAllByRole("link", { name: "RCT/26-27/000007" });
    expect(receipts[0]).toHaveAttribute("href", "/manage/payments/p1");
    expect(screen.getAllByRole("link", { name: "Bill INV/26-27/000001" })[0]).toHaveAttribute(
      "href",
      "/manage/invoices/i1",
    );
    await userEvent.setup().type(screen.getAllByRole("searchbox")[0]!, "Ganesh");
    await waitFor(() => expect(calls.at(-1)!.url.searchParams.get("search")).toBe("Ganesh"));
  });
});
