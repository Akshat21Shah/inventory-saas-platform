import { onlineManager } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor } from "@testing-library/react-native";
import { Pressable, Text } from "react-native";

import { ApiError, NETWORK_ERROR } from "@/lib/shared/errors";
import { renderScreen } from "@/tests/render";

import { CartProvider, useCart } from "./cart-state";

const mockSet = jest.fn();
jest.mock("@/lib/api/generated/endpoints/shop/shop", () => ({
  getShopCartRetrieveQueryKey: () => ["/api/v1/shop/cart/"],
  useShopCartRetrieve: () => ({
    data: undefined,
    isLoading: false,
    error: null,
    refetch: jest.fn(),
  }),
  shopCartLineSet: (...args: unknown[]) => mockSet(...args),
}));
const mockFiles = new Map<string, string>();
jest.mock("@/lib/storage/file-store", () => ({
  fileStore: {
    getItem: async (key: string) => mockFiles.get(key) ?? null,
    setItem: async (key: string, value: string) => void mockFiles.set(key, value),
  },
}));

function Taps() {
  const { setQuantity, quantityOf, pending } = useCart();
  return (
    <>
      <Pressable accessibilityRole="button" onPress={() => setQuantity("p1", "6")}>
        <Text>add</Text>
      </Pressable>
      <Text>{`qty ${quantityOf("p1")} ${pending ? "waiting" : "sent"}`}</Text>
    </>
  );
}

beforeEach(() => {
  mockFiles.clear();
  mockSet.mockReset().mockResolvedValue({ data: { lines: [] }, status: 200 });
  onlineManager.setOnline(true);
});

describe("The cart without a connection", () => {
  it("keeps a change on the phone and sends it when the connection is back", async () => {
    onlineManager.setOnline(false);
    await renderScreen(
      <CartProvider>
        <Taps />
      </CartProvider>,
    );
    await fireEvent.press(screen.getByRole("button"));
    await act(() => new Promise((resolve) => setTimeout(resolve, 500)));
    expect(mockSet).not.toHaveBeenCalled();
    expect(screen.getByText("qty 6 waiting")).toBeTruthy();
    expect(JSON.parse(mockFiles.get("cart-pending") ?? "{}")).toEqual({ p1: "6" });
    await act(async () => onlineManager.setOnline(true));
    await waitFor(() => expect(mockSet).toHaveBeenCalledWith("p1", { quantity: "6" }));
  });

  it("keeps a change whose request was cut off, without an error", async () => {
    mockSet.mockRejectedValueOnce(
      new ApiError(0, { code: NETWORK_ERROR, message: "Network unavailable", details: {} }),
    );
    await renderScreen(
      <CartProvider>
        <Taps />
      </CartProvider>,
    );
    await fireEvent.press(screen.getByRole("button"));
    await waitFor(() => expect(mockSet).toHaveBeenCalledTimes(1));
    expect(screen.getByText("qty 6 waiting")).toBeTruthy();
  });

  it("sends what was kept before the app was closed", async () => {
    mockFiles.set("cart-pending", JSON.stringify({ p1: "12" }));
    await renderScreen(
      <CartProvider>
        <Taps />
      </CartProvider>,
    );
    await waitFor(() => expect(mockSet).toHaveBeenCalledWith("p1", { quantity: "12" }));
  });
});
