import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { AnnouncementsPage } from "./announcements";
import {
  DocumentLinksCard,
  RateChangesCard,
  ReminderPauseCard,
  RetailerConsentCard,
} from "./cards";
import { DeliveriesPage } from "./deliveries";
import { NotificationRulesPage } from "./rules";
import { NotificationTextsPage } from "./texts";

let permissions = new Set<string>();
let languages: { code: string; native: string }[] = [];
vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({ me: { id: "u1", languages }, can: (code: string) => permissions.has(code) }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/manage/settings/notifications",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  permissions = new Set();
});

const estimate = (enabled: boolean, messages = 0, ready = true) => ({
  enabled,
  messages_30_days: messages,
  price: null,
  cost_30_days: null,
  templates: [{ audience: "SHOP", status: ready ? "APPROVED" : "SUBMITTED", ready }],
});

const matrix = {
  events: [
    {
      code: "invoice.issued",
      label: "Tax invoice issued",
      group: "billing",
      urgent: true,
      category: "UTILITY",
      shop_facing: true,
      customised: false,
      rules: [
        {
          recipient: "SHOP",
          permission: "",
          channels: ["IN_APP", "WHATSAPP", "EMAIL"],
          enabled: true,
          compulsory: true,
          is_default: true,
        },
      ],
      whatsapp: estimate(true, 12),
    },
    {
      code: "stock.alert_opened",
      label: "Stock low",
      group: "stock",
      urgent: false,
      category: "UTILITY",
      shop_facing: false,
      customised: true,
      rules: [
        {
          recipient: "STAFF_PERMISSION",
          permission: "stock.inward",
          channels: ["IN_APP"],
          enabled: true,
          compulsory: false,
          is_default: false,
        },
      ],
      whatsapp: estimate(false),
    },
  ],
  recipients: {
    SHOP: ["IN_APP", "WHATSAPP", "EMAIL", "SMS"],
    SALESPERSON: ["IN_APP", "WHATSAPP", "EMAIL"],
    COLLECTOR: ["IN_APP", "WHATSAPP", "EMAIL"],
    STAFF_PERMISSION: ["IN_APP", "WHATSAPP", "EMAIL"],
    OWNERS: ["IN_APP", "WHATSAPP", "EMAIL"],
  },
  whatsapp_feature_enabled: false,
  prices_set: false,
  whatsapp_cost_30_days: null,
  shops: { opted_in: 3, shops: 20 },
  permissions: [
    { code: "orders.manage", description: "Manage orders" },
    { code: "stock.inward", description: "Receive stock" },
  ],
};

describe("Who gets what", () => {
  it("shows each message's recipients, WhatsApp use and consent, and saves a change", async () => {
    const calls = mockApi({
      "/api/v1/notification-rules/": () => [200, matrix],
      "PUT /api/v1/notification-rules/invoice.issued/": () => [200, []],
    });
    renderWithIntl(<NotificationRulesPage />);
    expect(await screen.findByText("3 of 20 shops agreed to WhatsApp")).toBeVisible();
    expect(screen.getByText(/WhatsApp is turned off/)).toBeVisible();
    expect(screen.getByText("12 WhatsApp messages in 30 days")).toBeVisible();
    expect(screen.getByText("Receive stock")).toBeVisible(); // a permission, by its name
    expect(screen.getByText("Changed")).toBeVisible();
    expect(screen.getByText("Waits for quiet hours")).toBeVisible();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Change: Tax invoice issued" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("checkbox", { name: "WhatsApp" }));
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        rules: [
          {
            recipient: "SHOP",
            permission: "",
            channels: ["IN_APP", "EMAIL"],
            enabled: true,
            compulsory: true,
          },
        ],
      }),
    );
  });
});

describe("WhatsApp waiting for the provider's approval", () => {
  const waiting = (channels: string[]) => ({
    ...matrix,
    whatsapp_feature_enabled: true,
    whatsapp_approval_required: true,
    events: [
      {
        ...matrix.events[0]!,
        rules: [{ ...matrix.events[0]!.rules[0]!, channels }],
        whatsapp: estimate(true, 12, false),
      },
    ],
  });

  it("offers WhatsApp only once the text is approved", async () => {
    mockApi({ "/api/v1/notification-rules/": () => [200, waiting(["IN_APP", "EMAIL"])] });
    renderWithIntl(<NotificationRulesPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Change: Tax invoice issued" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("checkbox", { name: "WhatsApp" })).toBeDisabled();
    expect(
      within(dialog).getByText(
        "WhatsApp can be chosen once the provider approves this message's text.",
      ),
    ).toBeVisible();
  });

  it("warns where a rule already uses a text that isn't approved", async () => {
    mockApi({
      "/api/v1/notification-rules/": () => [200, waiting(["IN_APP", "WHATSAPP", "EMAIL"])],
    });
    renderWithIntl(<NotificationRulesPage />);
    expect(await screen.findByText("WhatsApp waiting for approval: not sent yet")).toBeVisible();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Change: Tax invoice issued" }));
    const dialog = await screen.findByRole("dialog");
    const box = within(dialog).getByRole("checkbox", { name: "WhatsApp" });
    expect(box).toBeEnabled(); // may be taken off
    expect(within(dialog).getByText(/isn't approved by the provider yet/)).toBeVisible();
  });
});

describe("Message texts", () => {
  it("edits the shop's and the office's words separately, with a preview", async () => {
    const shopText = {
      audience: "SHOP",
      channel: "IN_APP",
      subject: "Order {{ order_number }} accepted",
      body: "Your order was accepted.",
      source: "platform",
      editable: true,
      variables: ["distributor", "shop", "order_number"],
    };
    const calls = mockApi({
      "/api/v1/notification-rules/": () => [200, matrix],
      "/api/v1/notification-templates/order.accepted/": () => [
        200,
        [
          shopText,
          {
            ...shopText,
            channel: "WHATSAPP",
            subject: "",
            body: "{{ distributor }}: your order was accepted.",
            editable: false,
          },
          {
            ...shopText,
            audience: "STAFF",
            body: "{{ shop }}'s order was accepted.",
          },
        ],
      ],
      "POST /api/v1/notification-templates/preview/": () => [
        200,
        { subject: "Order ORD-2026-000123 accepted", body: "Sample" },
      ],
      "PUT /api/v1/notification-templates/order.accepted/IN_APP/": () => [200, []],
    });
    renderWithIntl(<NotificationTextsPage />);
    const shop = await screen.findByRole("region", { name: "To the shop" });
    const office = screen.getByRole("region", { name: "To your staff" });
    expect(within(shop).getByText("Approved template: set by the platform")).toBeVisible();
    expect(within(office).getByLabelText("Message")).toHaveValue(
      "{{ shop }}'s order was accepted.",
    );
    const user = userEvent.setup();
    await user.click(within(shop).getByRole("button", { name: "Insert order_number" }));
    expect(within(shop).getByLabelText("Message")).toHaveValue(
      "Your order was accepted.{{ order_number }}",
    );
    await user.click(within(shop).getByRole("button", { name: "Preview" }));
    expect(await within(shop).findByText("Order ORD-2026-000123 accepted")).toBeVisible();
    expect(calls.find((c) => c.path.endsWith("/preview/"))?.body).toMatchObject({
      audience: "SHOP",
    });
    await user.click(within(shop).getByRole("button", { name: "Save text" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        audience: "SHOP",
        locale: "en",
        subject: "Order {{ order_number }} accepted",
        body: "Your order was accepted.{{ order_number }}",
      }),
    );
    await user.click(within(office).getByRole("button", { name: "Save text" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "PUT").at(-1)?.body).toMatchObject({
        audience: "STAFF",
        body: "{{ shop }}'s order was accepted.",
      }),
    );
  });

  it("shows every language side by side and warns when only one has the distributor's words", async () => {
    languages = [
      { code: "en", native: "English" },
      { code: "hi", native: "हिन्दी" },
      { code: "mr", native: "मराठी" },
    ];
    const text = (locale: string, body: string, source: string) => ({
      audience: "SHOP",
      channel: "IN_APP",
      subject: "Order {{ order_number }}",
      body,
      source,
      editable: true,
      variables: ["order_number"],
      locale,
      edited_locales: ["en"],
    });
    const calls = mockApi({
      "/api/v1/notification-rules/": () => [200, matrix],
      "/api/v1/notification-templates/order.accepted/": (_body, url) => {
        const locale = url.searchParams.get("locale") ?? "en";
        const body = {
          en: "Our own words.",
          hi: "आपका ऑर्डर स्वीकार हुआ।",
          mr: "ऑर्डर स्वीकारली.",
        };
        const source = locale === "en" ? "tenant" : "platform";
        return [200, [text(locale, body[locale as "en"], source)]];
      },
      "PUT /api/v1/notification-templates/order.accepted/IN_APP/": () => [200, []],
    });
    renderWithIntl(<NotificationTextsPage />);
    const card = await screen.findByRole("region", { name: "In the app" });
    expect(within(card).getByRole("status")).toHaveTextContent(
      "You have your own wording in English only. हिन्दी, मराठी still use the standard text",
    );
    const hindi = within(card).getByRole("region", { name: "हिन्दी" });
    expect(within(hindi).getByLabelText("Message")).toHaveValue("आपका ऑर्डर स्वीकार हुआ।");
    const user = userEvent.setup();
    await user.click(within(hindi).getByRole("button", { name: "Save text" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ locale: "hi" }),
    );
    languages = [];
  });
});

const failed = {
  id: "n1",
  event_code: "invoice.issued",
  channel: "WHATSAPP",
  status: "FAILED",
  skip_reason: "",
  recipient_name: "Ganesh",
  shop_name: "Ganesh Kirana",
  address: "+919876500001",
  title: "Bill INV/26-27/000045",
  attempts: 6,
  last_error: "provider timeout",
  send_after: null,
  sent_at: null,
  created_at: "2026-09-29T09:00:00Z",
};

describe("Delivery log", () => {
  it("lists what failed and why, and tries again", async () => {
    const calls = mockApi({
      "/api/v1/notification-rules/": () => [200, matrix],
      "/api/v1/notification-deliveries/counts/": () => [
        200,
        { PENDING: 0, SENDING: 0, SENT: 10, FAILED: 1, SKIPPED: 2 },
      ],
      "/api/v1/notification-deliveries/": () => [
        200,
        { next: null, previous: null, results: [failed] },
      ],
      "/api/v1/notification-deliveries/n1/": () => [
        200,
        {
          ...failed,
          body: "Sharma: your bill…",
          provider: "",
          delivery_attempts: [
            {
              attempt_no: 1,
              provider: "",
              status: "FAILED",
              error: "provider timeout",
              duration_ms: 20,
              created_at: "2026-09-29T09:00:00Z",
            },
          ],
        },
      ],
      "POST /api/v1/notification-deliveries/n1/retry/": () => [
        200,
        { ...failed, status: "PENDING" },
      ],
    });
    renderWithIntl(<DeliveriesPage />);
    expect((await screen.findAllByText("provider timeout"))[0]).toBeVisible();
    expect(screen.getByText("Failed 1")).toBeVisible();
    const user = userEvent.setup();
    await user.click(screen.getAllByRole("button", { name: /Details: Bill/ })[0]!);
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Try 1")).toBeVisible();
    await user.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/retry/"))).toBe(true));
  });
});

describe("Announcements", () => {
  it("creates one", async () => {
    const calls = mockApi({
      "/api/v1/announcements/": () => [200, { next: null, previous: null, results: [] }],
      "POST /api/v1/announcements/": () => [201, {}],
    });
    renderWithIntl(<AnnouncementsPage />);
    expect(await screen.findByText("No announcements")).toBeVisible();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "New announcement" }));
    await user.type(screen.getByLabelText("Title"), "Diwali timings");
    await user.type(screen.getByLabelText("Message"), "Closed on Sunday.");
    await user.click(screen.getByRole("checkbox", { name: "Also send by WhatsApp" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const body = calls.find((c) => c.method === "POST")?.body as Record<string, unknown>;
      expect(body).toMatchObject({
        title: "Diwali timings",
        body: "Closed on Sunday.",
        is_active: true,
        send_whatsapp: true,
        ends_at: null,
      });
    });
  });
});

describe("Cards on existing pages", () => {
  it("records a shop's WhatsApp agreement only when staff confirm it", async () => {
    permissions = new Set(["retailers.view", "retailers.manage"]);
    const state = {
      opted_in: false,
      source: "",
      opted_in_at: null,
      opted_out_at: null,
      prompt: true,
      whatsapp_available: true,
    };
    const calls = mockApi({
      "/api/v1/retailers/r1/whatsapp-consent/": () => [200, state],
      "PUT /api/v1/retailers/r1/whatsapp-consent/": () => [
        200,
        { ...state, opted_in: true, source: "STAFF", opted_in_at: "2026-09-29T09:00:00Z" },
      ],
    });
    renderWithIntl(<RetailerConsentCard retailerId="r1" />);
    expect(await screen.findByText("Not agreed")).toBeVisible();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Record agreement" }));
    await user.click(
      screen.getByRole("switch", { name: "The shop agreed to get WhatsApp messages from us" }),
    );
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Record agreement" }),
    );
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        agreed: true,
        confirmed: true,
      }),
    );
    expect(await screen.findByText(/recorded by staff/)).toBeVisible();
  });

  it("pauses reminders with a reason", async () => {
    permissions = new Set(["credit.manage"]);
    const calls = mockApi({
      "/api/v1/retailers/r1/reminder-pause/": () => [200, { pause: null }],
      "POST /api/v1/retailers/r1/reminder-pause/": () => [
        200,
        {
          pause: {
            id: "p1",
            reason: "Disputed bill",
            until: null,
            created_at: "2026-09-29T09:00:00Z",
          },
        },
      ],
    });
    renderWithIntl(<ReminderPauseCard retailerId="r1" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Pause reminders" }));
    await user.type(screen.getByLabelText(/Why/), "Disputed bill");
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Pause reminders" }),
    );
    expect(await screen.findByText("Paused: Disputed bill")).toBeVisible();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      reason: "Disputed bill",
      until: null,
    });
  });

  it("shows a document's links and withdraws them; hidden without the permission", async () => {
    permissions = new Set(["invoices.manage"]);
    const calls = mockApi({
      "/api/v1/document-links/": () => [
        200,
        [
          {
            id: "l1",
            kind: "INVOICE",
            object_id: "i1",
            expires_at: "2026-10-29T09:00:00Z",
            revoked_at: null,
            open_count: 2,
            last_opened_at: null,
            created_at: "2026-09-29T09:00:00Z",
            is_live: true,
          },
        ],
      ],
      "POST /api/v1/document-links/revoke/": () => [200, { revoked: 1 }],
    });
    const { unmount } = renderWithIntl(<DocumentLinksCard kind="INVOICE" objectId="i1" />);
    expect(await screen.findByText(/Opened 2 times/)).toBeVisible();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Withdraw links" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Withdraw links" }),
    );
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/revoke/"))).toBe(true));
    unmount();
    permissions = new Set();
    renderWithIntl(<DocumentLinksCard kind="INVOICE" objectId="i1" />);
    expect(screen.queryByText("Shared links")).toBeNull();
  });

  it("lists upcoming GST changes on the dashboard", async () => {
    permissions = new Set(["products.view"]);
    mockApi({
      "/api/v1/tax/upcoming-rate-changes/": () => [
        200,
        [
          {
            product_id: "p1",
            product: "Tata Salt 1 kg",
            code: "TS1",
            effective_from: "2026-10-06",
            old_rate: "5.000",
            new_rate: "12.000",
          },
        ],
      ],
    });
    renderWithIntl(<RateChangesCard />);
    expect(await screen.findByText(/Tata Salt 1 kg: 5% → 12% from/)).toBeVisible();
  });
});
