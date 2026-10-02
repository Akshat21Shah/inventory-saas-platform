import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ShopFulfilment, ShopOrder } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { OrderPage } from "./orders";

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({ me: { id: "u1", retailer: { on_hold: false } }, can: () => false }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/shop/orders/o1",
  useSearchParams: () => new URLSearchParams(),
}));
afterEach(() => vi.unstubAllGlobals());

const shipment = (extra: Partial<ShopFulfilment> = {}): ShopFulfilment => ({
  id: "f1",
  number: "ORD-2026-000001/1",
  kind: "INITIAL",
  status: "DISPATCHED",
  created_at: "2026-09-27T10:00:00Z",
  packed_at: "2026-09-27T11:00:00Z",
  dispatched_at: "2026-09-27T12:00:00Z",
  delivered_at: null,
  vehicle_number: "MH12AB1234",
  transporter_name: "",
  lr_number: "",
  distance_km: null,
  cancelled_reason: "",
  needs_delivery_code: true,
  delivered_via: "",
  delivery_note: "",
  lines: [],
  delivery_code: "4821",
  can_confirm: true,
  ...extra,
});

const order = (fulfilments: ShopFulfilment[], status = "DISPATCHED"): ShopOrder =>
  ({
    id: "o1",
    number: "ORD-2026-000001",
    status,
    backorder_state: "NONE",
    hold_reason: "",
    retailer: "r1",
    retailer_name: "Ganesh Kirana",
    placed_via: "RETAILER_APP",
    placed_by_label: "",
    placed_at: "2026-09-27T10:00:00Z",
    accepted_at: "2026-09-27T10:30:00Z",
    closed_at: null,
    shipping_address: {},
    retailer_note: "",
    prices_include_tax: false,
    gross_total: "100.00",
    discount_total: "0.00",
    taxable_total: "100.00",
    tax_total: "5.00",
    round_off: "0.00",
    grand_total: "105.00",
    rejection_reason: "",
    cancellation_reason: "",
    items_to_follow: 0,
    lines: [],
    fulfilments,
    history: [],
    invoices: [],
    has_confirmation: false,
  }) as unknown as ShopOrder;

describe("Delivery in the shop app (ADR-057)", () => {
  it("shows the delivery code and lets the shop mark the shipment received", async () => {
    const calls = mockApi({
      "/api/v1/shop/orders/o1/": () => [200, order([shipment()])],
      "POST /api/v1/shop/fulfilments/f1/received/": () => [
        200,
        order(
          [shipment({ status: "DELIVERED", delivery_code: "", can_confirm: false })],
          "COMPLETED",
        ),
      ],
    });
    renderWithIntl(<OrderPage orderId="o1" />);
    expect(await screen.findByText("4821")).toBeVisible();
    expect(screen.getByLabelText("Delivery code 4 8 2 1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "I received it" }));
    await userEvent.click(await screen.findByRole("button", { name: "I received it" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    await waitFor(() => expect(screen.queryByText("4821")).toBeNull());
  });

  it("shows neither without a code or when the distributor marks deliveries", async () => {
    mockApi({
      "/api/v1/shop/orders/o1/": () => [
        200,
        order([shipment({ delivery_code: "", needs_delivery_code: false, can_confirm: false })]),
      ],
    });
    renderWithIntl(<OrderPage orderId="o1" />);
    expect(await screen.findByText("ORD-2026-000001/1")).toBeVisible();
    expect(screen.queryByRole("button", { name: "I received it" })).toBeNull();
    expect(screen.queryByText(/give this code/)).toBeNull();
  });
});
