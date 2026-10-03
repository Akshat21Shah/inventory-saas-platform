import { screen, fireEvent, waitFor } from "@testing-library/react-native";

import { ApiError, NETWORK_ERROR } from "@/lib/shared/errors";
import { renderScreen } from "@/tests/render";

import { CartScreen } from "./cart";

const mockPush = jest.fn();
jest.mock("expo-router", () => ({
  router: {
    push: (...args: unknown[]) => mockPush(...args),
    navigate: (...args: unknown[]) => mockPush(...args),
  },
  Link: ({ children }: { children: unknown }) => children,
}));
jest.mock("@/lib/auth/auth-provider", () => ({
  useAuth: () => ({ me: { id: "user-1", retailer: null } }),
}));
jest.mock("@/lib/cart/cart-state", () => ({
  useCart: () => ({
    pending: false,
    waiting: [],
    version: "p1:6",
    quantityOf: () => "6",
    setQuantity: jest.fn(),
  }),
}));

const QUOTE = {
  lines: [
    {
      product_id: "p1",
      is_free: false,
      quantity: "6.000",
      ready_qty: "6.000",
      later_qty: "0.000",
      unit_price: "232.60",
      discount_total: "0.00",
      line_total: "1465.38",
      offer: null,
      scheme: null,
      problems: [],
      product: {
        id: "p1",
        name: "Basmati Rice",
        thumbnail_url: null,
        min_order_qty: "6.000",
        order_multiple: "6.000",
        unit: { name: "Pieces" },
      },
    },
  ],
  problems: [],
  totals: {
    gross: "1395.60",
    discount: "0.00",
    tax: "69.78",
    round_off: "-0.38",
    grand_total: "1465.00",
  },
  can_place: true,
  expected_total: "1465.00",
  address_id: null,
  backorders_enabled: true,
  credit: { reason: "" },
};

const mockPlace = jest.fn();
const mockAttempt = jest.fn();
jest.mock("@/lib/api/generated/endpoints/shop/shop", () => ({
  getShopCartRetrieveQueryKey: () => ["/api/v1/shop/cart/"],
  useShopCartRetrieve: () => ({
    data: { data: QUOTE },
    isLoading: false,
    error: null,
    isRefetching: false,
    refetch: jest.fn(),
  }),
  useShopAddressesList: () => ({ data: { data: [] } }),
  shopOrdersPlace: (...args: unknown[]) => mockPlace(...args),
  shopCheckoutAttempt: (...args: unknown[]) => mockAttempt(...args),
  shopCartClear: jest.fn(),
  shopCartReduceToAvailable: jest.fn(),
}));

const keyOf = (call: unknown[]) =>
  (call[1] as { headers: Record<string, string> }).headers["Idempotency-Key"];

beforeEach(() => jest.clearAllMocks());

it("places the order once, with an Idempotency-Key, and opens it", async () => {
  mockPlace.mockResolvedValue({ data: { id: "order-1" } });
  await renderScreen(<CartScreen />);
  await fireEvent.press(screen.getByRole("button", { name: "Place order · ₹1,465.00" }));
  await waitFor(() =>
    expect(mockPush).toHaveBeenCalledWith({
      pathname: "/shop/(tabs)/(orders)/orders/[id]",
      params: { id: "order-1", placed: "1" },
    }),
  );
  expect(mockPlace.mock.calls[0][0]).toEqual({
    expected_total: "1465.00",
    address: null,
    note: "",
  });
  expect(keyOf(mockPlace.mock.calls[0])).toMatch(/^[0-9a-f]{32}$/);
});

it("after a dropped connection, asks the server about the same key before trying again", async () => {
  mockPlace.mockRejectedValueOnce(
    new ApiError(0, { code: NETWORK_ERROR, message: "", details: {} }),
  );
  await renderScreen(<CartScreen />);
  await fireEvent.press(screen.getByRole("button", { name: "Place order · ₹1,465.00" }));
  const retry = await screen.findByRole("button", { name: "Try again" });
  const key = keyOf(mockPlace.mock.calls[0]);
  // It went through after all: no second order.
  mockAttempt.mockResolvedValue({ data: { status: "placed", order: "order-1" } });
  await fireEvent.press(retry);
  await waitFor(() => expect(mockPush).toHaveBeenCalled());
  expect(mockAttempt).toHaveBeenCalledWith(key);
  expect(mockPlace).toHaveBeenCalledTimes(1);
});

it("retries with the same key when the first try never arrived", async () => {
  mockPlace
    .mockRejectedValueOnce(new ApiError(0, { code: NETWORK_ERROR, message: "", details: {} }))
    .mockResolvedValueOnce({ data: { id: "order-2" } });
  mockAttempt.mockResolvedValue({ data: { status: "unknown", order: null } });
  await renderScreen(<CartScreen />);
  await fireEvent.press(screen.getByRole("button", { name: "Place order · ₹1,465.00" }));
  await fireEvent.press(await screen.findByRole("button", { name: "Try again" }));
  await waitFor(() => expect(mockPlace).toHaveBeenCalledTimes(2));
  expect(keyOf(mockPlace.mock.calls[1])).toBe(keyOf(mockPlace.mock.calls[0]));
});
