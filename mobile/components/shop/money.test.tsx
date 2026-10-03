import { fireEvent, screen, waitFor } from "@testing-library/react-native";

import { renderScreen } from "@/tests/render";

import { OwedCard, PayBillButton } from "./money";

const mockPush = jest.fn();
jest.mock("expo-router", () => ({
  router: { push: (...args: unknown[]) => mockPush(...args) },
  Link: ({ children }: { children: unknown }) => children,
}));

let mockOnline = true;
let mockOutstanding: { balance: string; overdue: string } | null = null;
const mockStart = jest.fn();
jest.mock("@/lib/api/generated/endpoints/shop/shop", () => ({
  useShopAccount: () => ({ data: { data: { online_payments: mockOnline } } }),
  useShopHome: () => ({ data: { data: { outstanding: mockOutstanding } } }),
  shopCheckoutStart: (...args: unknown[]) => mockStart(...args),
}));

beforeEach(() => {
  mockOnline = true;
  mockOutstanding = null;
  mockPush.mockReset();
  mockStart.mockReset();
});

describe("Money in the app", () => {
  it("starts the bill's checkout with an Idempotency-Key and opens it", async () => {
    mockStart.mockResolvedValue({ data: { id: "c1" }, status: 200 });
    await renderScreen(<PayBillButton invoiceId="i1" balance="210.00" />);
    await fireEvent.press(screen.getByRole("button", { name: "Pay ₹210.00" }));
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith({
        pathname: "/shop/payments/checkout/[id]",
        params: { id: "c1" },
      }),
    );
    const [body, init] = mockStart.mock.calls[0] as [unknown, { headers: Record<string, string> }];
    expect(body).toEqual({ purpose: "INVOICE", invoice_id: "i1" });
    expect(init.headers["Idempotency-Key"]).toMatch(/^[0-9a-f]{32}$/);
  });

  it("offers Pay only while the distributor takes online payments and something is due", async () => {
    mockOnline = false;
    const first = await renderScreen(<PayBillButton invoiceId="i1" balance="210.00" />);
    expect(screen.queryByRole("button")).toBeNull();
    await first.unmount();
    mockOnline = true;
    await renderScreen(<PayBillButton invoiceId="i1" balance="0.00" />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows what the shop owes on home, and what is late", async () => {
    const first = await renderScreen(<OwedCard />);
    expect(screen.queryByText("You owe")).toBeNull(); // nothing owed
    await first.unmount();
    mockOutstanding = { balance: "1142.00", overdue: "326.00" };
    await renderScreen(<OwedCard />);
    expect(screen.getByText("You owe")).toBeTruthy();
    expect(screen.getByText("₹1,142.00")).toBeTruthy();
    expect(screen.getByText("₹326.00 is overdue")).toBeTruthy();
  });
});
