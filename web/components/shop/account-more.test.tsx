import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { ShopHelpPage, ShopPrivacyPage, ShopReturnsPage } from "./account-more";

afterEach(() => vi.unstubAllGlobals());

describe("More of the shop's account", () => {
  it("lists every return, each opening its bill", async () => {
    mockApi({
      "/api/v1/shop/return-requests/": () => [
        200,
        {
          next: null,
          previous: null,
          results: [
            {
              id: "r1",
              number: "RR-2026-000010",
              status: "REJECTED",
              reason: "DAMAGED",
              note: "",
              created_at: "2026-10-02T06:00:00Z",
              decided_at: "2026-10-02T07:00:00Z",
              decision_note: "Seal intact",
              retailer: { id: "s1", name: "Ganesh Kirana" },
              invoice: { id: "i1", number: "INV/26-27/000025" },
              credit_note: null,
              lines: [{ description: "Britannia Beauty Bar 200g", quantity: "1.000" }],
            },
          ],
        },
      ],
    });
    renderWithIntl(<ShopReturnsPage />);
    const link = await screen.findByRole("link", { name: /RR-2026-000010/ });
    expect(link).toHaveAttribute("href", "/shop/invoices/i1");
    expect(link).toHaveTextContent("1 Britannia Beauty Bar 200g");
    expect(link).toHaveTextContent("Not accepted: Seal intact");
  });

  it("says how to return when there are none", async () => {
    mockApi({
      "/api/v1/shop/return-requests/": () => [200, { next: null, previous: null, results: [] }],
    });
    renderWithIntl(<ShopReturnsPage />);
    expect(await screen.findByText("No returns yet")).toBeInTheDocument();
  });

  it("offers to call, WhatsApp or email the distributor", async () => {
    mockApi({
      "/api/v1/shop/distributor/": () => [
        200,
        { name: "Sharma Distributors", phone: "9876543210", email: "orders@sharma.example.com" },
      ],
    });
    renderWithIntl(<ShopHelpPage />);
    expect(await screen.findByRole("link", { name: "Call" })).toHaveAttribute(
      "href",
      "tel:9876543210",
    );
    expect(screen.getByRole("link", { name: "WhatsApp" })).toHaveAttribute(
      "href",
      "https://wa.me/919876543210",
    );
    expect(screen.getByRole("link", { name: "Email" })).toHaveAttribute(
      "href",
      "mailto:orders@sharma.example.com",
    );
  });

  it("links the privacy policy when the platform has one", async () => {
    mockApi({
      "/api/v1/app/config/": () => [
        200,
        {
          min_version: "0.0.0",
          latest_version: "",
          privacy_policy_url: "https://example.com/privacy",
        },
      ],
    });
    renderWithIntl(<ShopPrivacyPage />);
    expect(await screen.findByRole("link", { name: "Read the privacy policy" })).toHaveAttribute(
      "href",
      "https://example.com/privacy",
    );
    expect(screen.getByRole("link", { name: "Contact your distributor" })).toHaveAttribute(
      "href",
      "/shop/account/help",
    );
  });
});
