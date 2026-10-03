import { fireEvent, screen, waitFor } from "@testing-library/react-native";

import CheckoutScreen from "@/app/shop/(tabs)/(account)/payments/checkout/[id]";
import type { Checkout } from "@/lib/api/generated/model";
import { renderScreen } from "@/tests/render";

jest.mock("expo-router", () => ({
  router: { push: jest.fn(), back: jest.fn() },
  useLocalSearchParams: () => ({ id: "c1" }),
}));
jest.mock("expo-file-system", () => ({ File: jest.fn(), Paths: { cache: "cache" } }));
jest.mock("expo-sharing", () => ({ shareAsync: jest.fn() }));
const mockOpen = jest.fn();
jest.mock("expo-web-browser", () => ({
  openBrowserAsync: (...args: unknown[]) => mockOpen(...args),
}));

const checkout = (over: Partial<Checkout> = {}): Checkout => ({
  id: "c1",
  purpose: "INVOICE",
  invoice_id: "i1",
  invoice_number: "INV/26-27/000001",
  amount: "210.00",
  status: "CREATED",
  provider: "MOCK",
  checkout: {},
  expires_at: "2026-10-04T06:00:00Z",
  last_error: "",
  payment_id: null,
  receipt_number: "",
  created_at: "2026-10-04T05:30:00Z",
  paid_at: null,
  awaiting_confirmation: false,
  ...over,
});

let mockCheckout = checkout();
const mockRefetch = jest.fn();
const mockBrowserLink = jest.fn();
jest.mock("@/lib/api/generated/endpoints/shop/shop", () => ({
  useShopCheckout: () => ({
    data: { data: mockCheckout },
    isLoading: false,
    error: null,
    isRefetching: false,
    refetch: mockRefetch,
  }),
  shopCheckoutBrowser: (...args: unknown[]) => mockBrowserLink(...args),
  shopPaymentsReceipt: jest.fn(),
}));

beforeEach(() => {
  mockCheckout = checkout();
  mockRefetch.mockReset();
  mockOpen.mockReset();
  mockBrowserLink.mockReset();
});

describe("Paying from the app", () => {
  it("opens this checkout's payment page in a Custom Tab, then asks the server", async () => {
    mockBrowserLink.mockResolvedValue({
      data: { url: "http://sharma.test/pay/c1#code=one-time", expires_at: "" },
      status: 200,
    });
    mockOpen.mockResolvedValue({ type: "dismiss" });
    await renderScreen(<CheckoutScreen />);
    expect(screen.getByText("₹210.00")).toBeTruthy();
    expect(screen.getByText("For bill INV/26-27/000001")).toBeTruthy();
    await fireEvent.press(screen.getByRole("button", { name: "Pay ₹210.00 now" }));
    await waitFor(() => expect(mockRefetch).toHaveBeenCalled());
    expect(mockBrowserLink).toHaveBeenCalledWith("c1");
    // In the app's own task, so the page's "Back to the app" closes the tab.
    expect(mockOpen).toHaveBeenCalledWith("http://sharma.test/pay/c1#code=one-time", {
      createTask: false,
      showTitle: true,
    });
  });

  it("shows paid, with the receipt, only from the server's answer", async () => {
    mockCheckout = checkout({ status: "PAID", payment_id: "p1", receipt_number: "RCT/1" });
    await renderScreen(<CheckoutScreen />);
    expect(screen.getByText("Paid")).toBeTruthy();
    expect(screen.getByText("Thank you. Receipt RCT/1.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download receipt" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Pay ₹210.00 now" })).toBeNull();
  });

  it("says when the payment wasn't finished in time", async () => {
    mockCheckout = checkout({ status: "EXPIRED" });
    await renderScreen(<CheckoutScreen />);
    expect(screen.getByText("This payment wasn't finished in time.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start again" })).toBeTruthy();
  });
});
