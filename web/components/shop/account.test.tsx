import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { ShopAccountPage, ShopBillsPage, ShopPaymentsPage } from "./account";

const signOut = vi.fn();
vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({ me: { id: "u1" }, signOut, can: () => false }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/shop/account",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => vi.unstubAllGlobals());

const buckets = {
  not_due: "0.00",
  d0_30: "0.00",
  d31_60: "0.00",
  d61_90: "0.00",
  d90_plus: "0.00",
};

describe("My account", () => {
  it("shows what the shop owes, that orders wait for overdue bills, and signs out", async () => {
    mockApi({
      "/api/v1/shop/account/": () => [
        200,
        {
          position: {
            balance: "950.00",
            owed: "950.00",
            overdue: "950.00",
            unapplied_credit: "0.00",
            oldest_due: "2026-08-01",
            days_overdue: 58,
          },
          credit_limit: "5000.00",
          available_credit: "4050.00",
          ageing_basis: "INVOICE_DATE",
          ageing: buckets,
          overdue_bills: 1,
          orders_blocked_for_overdue: true,
        },
      ],
    });
    renderWithIntl(<ShopAccountPage />);
    expect(
      await screen.findByText(/New orders wait for your distributor's approval/),
    ).toBeVisible();
    expect(screen.getByText("₹4,050.00")).toBeVisible();
    for (const name of ["My bills", "Statement", "My payments", "Your profile"]) {
      expect(screen.getByRole("link", { name })).toBeVisible();
    }
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));
    expect(signOut).toHaveBeenCalled();
  });
});

describe("My bills", () => {
  it("lists bills to pay, and how late they are", async () => {
    const calls = mockApi({
      "/api/v1/shop/invoices/": () => [
        200,
        {
          next: null,
          previous: null,
          results: [
            {
              id: "i1",
              number: "INV/26-27/000001",
              invoice_date: "2026-07-02",
              due_date: "2026-08-01",
              retailer: { id: "r1", code: "R-00001", shop_name: "Ganesh Kirana" },
              order: { id: "o1", number: "ORD-2026-000001" },
              grand_total: "950.00",
              balance_due: "950.00",
              payment_status: "UNPAID",
              days_overdue: 58,
              issued_trigger: "ON_DISPATCH",
              pdf_status: "READY",
              einvoice_status: "NOT_APPLICABLE",
              status: "ISSUED",
            },
          ],
        },
      ],
    });
    renderWithIntl(<ShopBillsPage />);
    expect(await screen.findByText(/58 days late/)).toBeVisible();
    expect(screen.getByRole("link", { name: /INV\/26-27\/000001/ })).toHaveAttribute(
      "href",
      "/shop/invoices/i1",
    );
    await userEvent.setup().click(screen.getByRole("tab", { name: "Overdue" }));
    expect(calls.at(-1)!.url.searchParams.get("state")).toBe("overdue");
  });
});

describe("My payments", () => {
  it("says when a cheque bounced and offers the receipt", async () => {
    mockApi({
      "/api/v1/shop/payments/": () => [
        200,
        {
          next: null,
          previous: null,
          results: [
            {
              id: "p1",
              number: "RCT/26-27/000001",
              payment_date: "2026-09-20",
              retailer: { id: "r1", code: "R-00001", shop_name: "Ganesh Kirana" },
              amount: "500.00",
              mode: "CHEQUE",
              status: "BOUNCED",
              credit_timing: "ON_RECEIPT",
              unapplied_amount: "0.00",
              handover_status: "WITH_SALESMAN",
              collected_by_name: "Ravi",
              receipt_pdf_status: "READY",
              dated_in_previous_financial_year: false,
              held_as_credit_while_advances_off: null,
            },
          ],
        },
      ],
    });
    renderWithIntl(<ShopPaymentsPage />);
    expect(await screen.findByText("Cheque bounced")).toBeVisible();
    expect(screen.getByText(/collected by Ravi/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Receipt" })).toBeVisible();
  });
});
