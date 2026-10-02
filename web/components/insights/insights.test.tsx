import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ShopActivity, ShopContact } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";
import { setViewport } from "@/tests/viewport";

import { ShopActivityCard, ShopActivityPage } from "./shop-activity";

let permissions = new Set<string>();
const auth = {
  me: { id: "u1", full_name: "Priya", tenant: { name: "Sharma Distributors" } },
  can: (p: string) => permissions.has(p),
  feature: () => true,
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/manage/retailers/activity",
  useSearchParams: () => new URLSearchParams(),
}));

beforeEach(() => {
  permissions = new Set(["retailers.view", "orders.create_on_behalf"]);
  toast.success.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

const activity = (extra: Partial<ShopActivity> = {}): ShopActivity => ({
  retailer_id: "r1",
  retailer_code: "SH-0001",
  shop_name: "Ganesh Kirana",
  owner_name: "Ganesh Patil",
  mobile: "+919876500001",
  shop_status: "ACTIVE",
  salesperson_name: "Ravi",
  segment: "DORMANT",
  computed_at: "2026-10-01T20:15:00Z",
  first_order_date: "2026-03-01",
  last_order_date: "2026-08-01",
  days_since_last: 61,
  usual_gap_days: "7.0",
  orders_90: 2,
  orders_prev_90: 6,
  value_90: "1050.00",
  value_prev_90: "3150.00",
  last_contact_at: null,
  last_contact_outcome: null,
  last_contact_by: null,
  ...extra,
});

const page = (results: unknown[]) =>
  [200, { next: null, previous: null, results }] as [number, unknown];
const salespeople = {
  "/api/v1/retailers/salespeople/": () => [200, []] as [number, unknown],
};

describe("ShopActivityPage", () => {
  it("lists the shops to win back with what to do about each", async () => {
    const calls = mockApi({
      ...salespeople,
      "/api/v1/shop-activity/": () =>
        page([
          activity(),
          activity({
            retailer_id: "r2",
            shop_name: "Om Stores",
            segment: "NEVER_ORDERED",
            last_order_date: null,
            days_since_last: null,
            usual_gap_days: null,
            orders_90: 0,
            orders_prev_90: 0,
            value_90: "0.00",
          }),
        ]),
    });
    renderWithIntl(<ShopActivityPage />);
    const row = (await screen.findByText("Ganesh Kirana")).closest("tr")!;
    expect(within(row).getByText("Stopped ordering")).toBeInTheDocument();
    expect(within(row).getByText("61 days ago")).toBeInTheDocument();
    expect(within(row).getByText("every 7 days")).toBeInTheDocument();
    expect(within(row).getByText("2 (was 6)")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Call Ganesh Kirana" })).toHaveAttribute(
      "href",
      "tel:+919876500001",
    );
    const whatsapp = within(row).getByRole("link", { name: "WhatsApp Ganesh Kirana" });
    expect(whatsapp.getAttribute("href")).toContain("https://wa.me/919876500001?text=Namaste");
    expect(decodeURIComponent(whatsapp.getAttribute("href")!)).toContain(
      "this is Priya from Sharma Distributors",
    );
    expect(within(row).getByRole("link", { name: "Place an order" })).toHaveAttribute(
      "href",
      "/manage/orders/new?shop=r1",
    );
    const never = screen.getByText("Om Stores").closest("tr")!;
    expect(within(never).getByText("Never ordered")).toBeInTheDocument();
    expect(within(never).getByText("Never")).toBeInTheDocument();
    // The win-back list is asked for first.
    expect(calls.find((c) => c.path === "/api/v1/shop-activity/")!.url.search).toContain(
      "win_back=true",
    );
  });

  it("hides the value column without a sales permission and ordering without its own", async () => {
    permissions = new Set(["retailers.view"]);
    mockApi({
      ...salespeople,
      "/api/v1/shop-activity/": () => page([activity({ value_90: null })]),
    });
    renderWithIntl(<ShopActivityPage />);
    await screen.findByText("Ganesh Kirana");
    expect(screen.queryByRole("columnheader", { name: "Value (90 days)" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Place an order" })).toBeNull();
  });

  it("logs a contact", async () => {
    const calls = mockApi({
      ...salespeople,
      "/api/v1/shop-activity/": () => page([activity()]),
      "POST /api/v1/retailers/r1/contacts/": () => [
        201,
        { id: "c1", created_at: "", channel: "CALL", outcome: "WILL_ORDER", note: "", by_name: "" },
      ],
    });
    renderWithIntl(<ShopActivityPage />);
    const row = (await screen.findByText("Ganesh Kirana")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Log a contact" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("combobox", { name: "What happened" }));
    await userEvent.click(await screen.findByRole("option", { name: "Will order" }));
    await userEvent.type(within(dialog).getByLabelText("Note"), "After Diwali");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        channel: "CALL",
        outcome: "WILL_ORDER",
        note: "After Diwali",
      }),
    );
    expect(toast.success).toHaveBeenCalledWith(
      "Saved. Ganesh Kirana leaves the win-back list for a while.",
    );
  });

  it("says when nobody needs winning back", async () => {
    mockApi({ ...salespeople, "/api/v1/shop-activity/": () => page([]) });
    renderWithIntl(<ShopActivityPage />);
    expect(await screen.findByText("Nobody to win back")).toBeInTheDocument();
  });

  it("shows cards with the actions on a phone", async () => {
    setViewport(360);
    mockApi({ ...salespeople, "/api/v1/shop-activity/": () => page([activity()]) });
    renderWithIntl(<ShopActivityPage />);
    await screen.findByText("Ganesh Kirana");
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("link", { name: "Call Ganesh Kirana" })).toBeInTheDocument();
  });
});

describe("ShopActivityCard", () => {
  it("shows the shop's ordering and the contacts logged", async () => {
    const contact: ShopContact = {
      id: "c1",
      created_at: "2026-10-01T06:00:00Z",
      channel: "VISIT",
      outcome: "WILL_ORDER",
      note: "Will order on Monday",
      by_name: "Ravi",
    };
    mockApi({
      "/api/v1/retailers/r1/activity/": () => [
        200,
        { activity: activity({ segment: "SLOWING" }), contacts: [contact] },
      ],
    });
    renderWithIntl(<ShopActivityCard retailerId="r1" />);
    expect(await screen.findByText("Slowing down")).toBeInTheDocument();
    expect(screen.getByText("Visit · Will order")).toBeInTheDocument();
    expect(screen.getByText("Will order on Monday")).toBeInTheDocument();
  });

  it("before the first night's figures", async () => {
    mockApi({ "/api/v1/retailers/r1/activity/": () => [200, { activity: null, contacts: [] }] });
    renderWithIntl(<ShopActivityCard retailerId="r1" />);
    expect(await screen.findByText("Worked out tonight.")).toBeInTheDocument();
    expect(screen.getByText("No contacts logged yet.")).toBeInTheDocument();
  });
});
