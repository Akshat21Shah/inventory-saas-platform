import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DistributorDashboard } from "@/components/orders/dashboard";
import type { DocumentSeries } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { DocumentNumbering } from "./numbering";

const permissions = new Set<string>();
const auth = { me: { id: "u1", tenant: { id: "t1" } }, can: (p: string) => permissions.has(p) };
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/manage",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  permissions.clear();
});

const series = (prefix: string): DocumentSeries[] => [
  {
    document_type: "INVOICE",
    prefix,
    fy: "2026-27",
    next_number: `${prefix}/26-27/000013`,
    issued: 12,
  },
  {
    document_type: "REFUND",
    prefix: "RFD",
    fy: "2026-27",
    next_number: "RFD/26-27/000001",
    issued: 0,
  },
];

describe("Document numbers", () => {
  it("shows the next numbers and changes a prefix for those who manage settings", async () => {
    permissions.add("settings.manage");
    const calls = mockApi({
      "/api/v1/settings/document-series/": () => [200, series("INV")],
      "PATCH /api/v1/settings/document-series/": () => [200, series("SD")],
    });
    const user = userEvent.setup();
    renderWithIntl(<DocumentNumbering />);
    expect(await screen.findByText(/Next: INV\/26-27\/000013 · 12 issued this year/)).toBeVisible();
    const [prefix] = screen.getAllByLabelText("Prefix");
    await user.clear(prefix!);
    await user.type(prefix!, "sd");
    await user.click(screen.getAllByRole("button", { name: "Save" })[0]!);
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
        document_type: "INVOICE",
        prefix: "SD",
      }),
    );
    expect(await screen.findByText(/Next: SD\/26-27\/000013/)).toBeVisible();
  });

  it("is read-only for everyone else", async () => {
    mockApi({ "/api/v1/settings/document-series/": () => [200, series("INV")] });
    renderWithIntl(<DocumentNumbering />);
    expect(await screen.findByText("Tax invoices")).toBeVisible();
    expect(screen.queryByLabelText("Prefix")).toBeNull();
  });
});

describe("Dashboard", () => {
  it("adds money to collect for those who see receivables", async () => {
    permissions.add("ledger.view");
    mockApi({
      "/api/v1/receivables/summary/": () => [
        200,
        {
          owed: "4251.00",
          overdue: "950.00",
          shops_overdue: 1,
          due_this_week: "0.00",
          unapplied_credit: "1498.00",
          collections_pending_handover: "500.00",
        },
      ],
    });
    renderWithIntl(<DistributorDashboard />);
    expect(await screen.findByText("Money to collect")).toBeVisible();
    expect(await screen.findByText("₹4,251.00")).toBeVisible();
    expect(screen.getByRole("link", { name: /With salesmen/ })).toHaveAttribute(
      "href",
      "/manage/payments/handover",
    );
  });
});
