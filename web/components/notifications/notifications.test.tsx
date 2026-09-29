import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { NotificationBell } from "./bell";
import { NotificationInbox } from "./inbox";

const push = vi.fn();
vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({ me: { id: "u1" }, can: () => true }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/shop/notifications",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  push.mockReset();
});

const message = (id: string, read: boolean, path = "/shop/orders/o1") => ({
  id,
  event_code: "order.accepted",
  title: `Order ORD-2026-00000${id} accepted`,
  body: "Your order was accepted.",
  path,
  is_read: read,
  read_at: read ? "2026-09-29T10:00:00Z" : null,
  created_at: "2026-09-29T09:00:00Z",
});

describe("Notification inbox", () => {
  it("opens a message: marks it read and goes to its page", async () => {
    const calls = mockApi({
      "/api/v1/shop/notifications/": () => [
        200,
        { next: null, previous: null, results: [message("1", false), message("2", true)] },
      ],
      "/api/v1/shop/notifications/unread-count/": () => [200, { unread: 1 }],
      "POST /api/v1/shop/notifications/1/read/": () => [200, { marked: 1 }],
      "POST /api/v1/shop/notifications/read-all/": () => [200, { marked: 1 }],
    });
    renderWithIntl(<NotificationInbox scope="shop" />);
    const unread = await screen.findByRole("button", { name: /ORD-2026-000001 accepted.*Unread/ });
    expect(await screen.findByText("1 unread message")).toBeVisible();
    const user = userEvent.setup();
    await user.click(unread);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/shop/orders/o1"));
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/1/read/"))).toBe(true);
    await user.click(screen.getByRole("button", { name: "Mark all as read" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/shop/notifications/read-all/")).toBe(true),
    );
  });

  it("filters unread and shows an empty state", async () => {
    const calls = mockApi({
      "/api/v1/notifications/": () => [200, { next: null, previous: null, results: [] }],
      "/api/v1/notifications/unread-count/": () => [200, { unread: 0 }],
    });
    renderWithIntl(<NotificationInbox scope="staff" />);
    expect(await screen.findByText("No messages yet")).toBeVisible();
    expect(screen.getByText("You're all caught up.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Mark all as read" })).toBeDisabled();
    await userEvent.setup().click(screen.getByRole("tab", { name: "Unread" }));
    expect(await screen.findByText("No unread messages")).toBeVisible();
    expect(calls.some((c) => c.url.searchParams.get("unread") === "true")).toBe(true);
  });

  it("shows a friendly error", async () => {
    mockApi({ "/api/v1/notifications/unread-count/": () => [200, { unread: 0 }] });
    renderWithIntl(<NotificationInbox scope="staff" />);
    expect(await screen.findByRole("alert")).toBeVisible();
  });
});

describe("Notification bell", () => {
  it("shows the unread count and links to the inbox", async () => {
    mockApi({ "/api/v1/notifications/unread-count/": () => [200, { unread: 3 }] });
    renderWithIntl(<NotificationBell scope="staff" />);
    const bell = await screen.findByRole("link", { name: "Notifications: 3 unread" });
    expect(bell).toHaveAttribute("href", "/manage/notifications");
  });
});
