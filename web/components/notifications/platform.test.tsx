import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { PlatformFailuresPage, PlatformTextsPage } from "./platform";

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({ me: { id: "admin" }, can: () => true }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/platform/notifications",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => vi.unstubAllGlobals());

const template = (channel: string, body: string, extra = {}) => ({
  id: `t-${channel}`,
  event_code: "order.accepted",
  audience: "SHOP",
  channel,
  locale: "en",
  subject: channel === "IN_APP" ? "Order {{ order_number }} accepted" : "",
  body,
  whatsapp_template_name: "",
  whatsapp_language: "",
  whatsapp_category: "",
  variables: [],
  updated_at: "2026-09-29T09:00:00Z",
  submitted_by_default: channel === "WHATSAPP" ? true : null,
  ...extra,
});

describe("Default message texts", () => {
  it("saves a WhatsApp text with its approved template name and category", async () => {
    const calls = mockApi({
      "/api/v1/platform/notification-templates/": () => [
        200,
        [
          template("IN_APP", "Your order was accepted."),
          template("WHATSAPP", "{{ distributor }}: order {{ order_number }} accepted.", {
            whatsapp_template_name: "b2b_order_accepted",
            whatsapp_category: "UTILITY",
            variables: ["distributor", "order_number"],
          }),
        ],
      ],
      "PUT /api/v1/platform/notification-templates/order.accepted/WHATSAPP/": () => [200, {}],
    });
    renderWithIntl(<PlatformTextsPage />);
    expect(
      await screen.findByText("Parameters, in order: distributor, order_number"),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: "To the shop · WhatsApp · en" })).toBeVisible();
    expect(screen.getByText("First submission batch")).toBeVisible();
    expect(screen.queryByText("Optional, not submitted by default")).toBeNull();
    const user = userEvent.setup();
    const name = screen.getByLabelText("Approved template name");
    await user.clear(name);
    await user.type(name, "b2b_order_accepted_v2");
    await user.click(screen.getAllByRole("button", { name: "Save" })[1]!);
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
        audience: "SHOP",
        body: "{{ distributor }}: order {{ order_number }} accepted.",
        whatsapp_template_name: "b2b_order_accepted_v2",
        whatsapp_category: "UTILITY",
      }),
    );
  });
});

describe("Failed messages", () => {
  it("lists failures across businesses and tries one again", async () => {
    const calls = mockApi({
      "/api/v1/platform/notification-failures/": () => [
        200,
        {
          next: null,
          previous: null,
          results: [
            {
              id: "n1",
              event_code: "invoice.issued",
              channel: "WHATSAPP",
              status: "FAILED",
              skip_reason: "",
              recipient_name: "",
              shop_name: "Ganesh Kirana",
              address: "+919876500001",
              title: "Bill INV/26-27/000045",
              attempts: 6,
              last_error: "provider timeout",
              send_after: null,
              sent_at: null,
              created_at: "2026-09-29T09:00:00Z",
              tenant_id: "t1",
              tenant_name: "Sharma Distributors",
            },
          ],
        },
      ],
      "POST /api/v1/platform/notification-failures/n1/retry/": () => [200, {}],
    });
    renderWithIntl(<PlatformFailuresPage />);
    expect((await screen.findAllByText("Sharma Distributors"))[0]).toBeVisible();
    await userEvent.setup().click(screen.getAllByRole("button", { name: /Try again: Bill/ })[0]!);
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/retry/"))).toBe(true));
  });
});
