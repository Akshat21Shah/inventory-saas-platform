import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { ShopAnnouncements, ShopMessagesPage, WhatsAppPrompt } from "./messages";

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({
    me: { id: "u1", phone: "+919876500001", tenant: { name: "Sharma Distributors" } },
    can: () => false,
  }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/shop/account/messages",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => vi.unstubAllGlobals());

const consent = (over: Record<string, unknown> = {}) => ({
  opted_in: false,
  source: "",
  opted_in_at: null,
  opted_out_at: null,
  prompt: true,
  whatsapp_available: true,
  ...over,
});

const preferences = [
  {
    event: "order.accepted",
    label: "Order accepted",
    group: "orders",
    compulsory: false,
    channels: [
      { channel: "IN_APP", enabled: true, locked: true },
      { channel: "WHATSAPP", enabled: true, locked: false },
    ],
  },
  {
    event: "invoice.issued",
    label: "Tax invoice issued",
    group: "billing",
    compulsory: true,
    channels: [
      { channel: "IN_APP", enabled: true, locked: true },
      { channel: "EMAIL", enabled: true, locked: true },
    ],
  },
];

describe("Messages page", () => {
  it("locks in-app and required messages, and switches the rest", async () => {
    const calls = mockApi({
      "/api/v1/shop/whatsapp-consent/": () => [200, consent({ opted_in: true, prompt: false })],
      "/api/v1/shop/notification-preferences/": () => [200, preferences],
      "PUT /api/v1/shop/notification-preferences/": () => [200, preferences],
    });
    renderWithIntl(<ShopMessagesPage />);
    const whatsapp = await screen.findByRole("switch", { name: "Order accepted: WhatsApp" });
    expect(screen.getByRole("switch", { name: "Order accepted: In the app" })).toBeDisabled();
    expect(screen.getByRole("switch", { name: "New bill: Email" })).toBeDisabled();
    expect(screen.getByText("Always sent")).toBeVisible();
    await userEvent.setup().click(whatsapp);
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        event: "order.accepted",
        channel: "WHATSAPP",
        enabled: false,
      }),
    );
  });

  it("turns WhatsApp on, and keeps WhatsApp choices off until then", async () => {
    const calls = mockApi({
      "/api/v1/shop/whatsapp-consent/": () => [200, consent({ prompt: false })],
      "PUT /api/v1/shop/whatsapp-consent/": () => [200, consent({ opted_in: true })],
      "/api/v1/shop/notification-preferences/": () => [200, preferences],
    });
    renderWithIntl(<ShopMessagesPage />);
    expect(await screen.findByRole("switch", { name: "Order accepted: WhatsApp" })).toBeDisabled();
    await userEvent
      .setup()
      .click(screen.getByRole("switch", { name: "Send me WhatsApp messages" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ agreed: true }),
    );
  });

  it("says when the distributor doesn't send WhatsApp", async () => {
    mockApi({
      "/api/v1/shop/whatsapp-consent/": () => [200, consent({ whatsapp_available: false })],
      "/api/v1/shop/notification-preferences/": () => [200, []],
    });
    renderWithIntl(<ShopMessagesPage />);
    expect(
      await screen.findByText("Your distributor doesn't send WhatsApp messages yet."),
    ).toBeVisible();
  });
});

describe("WhatsApp question after sign-in", () => {
  it("asks once: yes records consent", async () => {
    const calls = mockApi({
      "/api/v1/shop/whatsapp-consent/": () => [200, consent()],
      "PUT /api/v1/shop/whatsapp-consent/": () => [200, consent({ opted_in: true, prompt: false })],
    });
    renderWithIntl(<WhatsAppPrompt />);
    expect(await screen.findByText(/Sharma Distributors can send you/)).toBeVisible();
    expect(screen.getByText(/\+919876500001/)).toBeVisible();
    await userEvent.setup().click(screen.getByRole("button", { name: "Yes, send on WhatsApp" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("not now: remembered, not asked again", async () => {
    const calls = mockApi({
      "/api/v1/shop/whatsapp-consent/": () => [200, consent()],
      "POST /api/v1/shop/whatsapp-consent/prompted/": () => [200, consent({ prompt: false })],
    });
    renderWithIntl(<WhatsAppPrompt />);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Not now" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/prompted/"))).toBe(true));
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("isn't shown once answered, or without WhatsApp", async () => {
    mockApi({ "/api/v1/shop/whatsapp-consent/": () => [200, consent({ prompt: false })] });
    renderWithIntl(<WhatsAppPrompt />);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("Announcements", () => {
  it("shows the distributor's notices", async () => {
    mockApi({
      "/api/v1/shop/announcements/": () => [
        200,
        [
          {
            id: "a1",
            title: "Diwali timings",
            body: "Orders after 2 PM go the next day.",
            starts_at: "2026-09-29T00:00:00Z",
            ends_at: null,
          },
        ],
      ],
    });
    renderWithIntl(<ShopAnnouncements />);
    expect(await screen.findByText("Diwali timings")).toBeVisible();
    expect(screen.getByRole("region", { name: "From your distributor" })).toBeVisible();
  });
});
