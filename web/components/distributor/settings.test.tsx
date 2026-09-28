import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HostBrandingProvider } from "@/components/auth/tenant-branding";
import type { Setting } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { BrandingSettings } from "./branding-settings";
import { BusinessSettings } from "./business-settings";
import { PolicySettings } from "./policy-settings";
import { POLICY_GROUPS } from "./settings-nav";

const auth = {
  permissions: [] as string[],
  me: { impersonation: null } as Record<string, unknown>,
  can: (code: string) => auth.permissions.includes(code),
  reloadMe: vi.fn(async () => {}),
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/manage/settings/business",
}));

afterEach(() => {
  vi.unstubAllGlobals();
  auth.me = { impersonation: null };
});

const business = {
  name: "Sharma Distributors",
  legal_name: "Sharma Distributors LLP",
  gstin: "27AAKFS1234A1ZM",
  pan: "AAKFS1234A",
  state_code: "27",
  registration_type: "REGULAR",
  slug: "sharma",
  address_line1: "14 Laxmi Road",
  address_line2: "",
  city: "Pune",
  pincode: "411030",
  email: "accounts@sharma.example.com",
  phone: "02024451234",
  invoice_terms: "",
  invoice_footer: "",
  signatory_name: "",
  has_signatory_image: false,
  gst_identity_locked: false,
};

const bank = {
  bank_account_name: "Sharma Distributors LLP",
  bank_account_number_masked: "XXXXXX4321",
  bank_ifsc: "HDFC0001234",
  bank_name: "HDFC Bank",
  bank_branch: "Laxmi Road",
  upi_id: "",
};

describe("BusinessSettings", () => {
  it("is read-only without settings.manage and never asks for bank details", async () => {
    auth.permissions = ["orders.view"];
    const calls = mockApi({
      "/api/v1/settings/business/": () => [200, business],
      "/api/v1/public/states/": () => [200, [{ code: "27", name: "Maharashtra" }]],
    });
    renderWithIntl(<BusinessSettings />);
    expect(await screen.findByText(/only the owner can change/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^business name/i)).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: /save/i })).not.toBeInTheDocument();
    expect(calls.some((c) => c.path.includes("bank-details"))).toBe(false);
  });

  it("keeps the GST identity read-only after the first invoice (task 5.13)", async () => {
    auth.permissions = ["settings.manage"];
    mockApi({
      "/api/v1/settings/business/": () => [200, { ...business, gst_identity_locked: true }],
      "/api/v1/settings/bank-details/": () => [200, bank],
      "/api/v1/public/states/": () => [200, [{ code: "27", name: "Maharashtra" }]],
    });
    renderWithIntl(<BusinessSettings />);
    expect(await screen.findByText(/fixed now that you have issued invoices/i)).toBeVisible();
    expect(screen.getByLabelText(/^gstin/i)).toHaveAttribute("readonly");
    expect(screen.getByLabelText(/^legal name/i)).toHaveAttribute("readonly");
    expect(screen.getByLabelText(/^city/i)).not.toHaveAttribute("readonly");
  });

  it("sends only changed fields, and a new account number only when typed", async () => {
    auth.permissions = ["settings.manage"];
    const calls = mockApi({
      "/api/v1/settings/business/": () => [200, business],
      "PATCH /api/v1/settings/business/": (body) => [200, { ...business, ...(body as object) }],
      "/api/v1/settings/bank-details/": () => [200, bank],
      "PUT /api/v1/settings/bank-details/": (body) => [200, { ...bank, ...(body as object) }],
      "/api/v1/public/states/": () => [200, [{ code: "27", name: "Maharashtra" }]],
    });
    renderWithIntl(<BusinessSettings />);
    const user = userEvent.setup();
    const city = await screen.findByLabelText(/^city/i);
    await user.clear(city);
    await user.type(city, "Pimpri");
    await user.click(screen.getByRole("button", { name: /^save changes$/i }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === "/api/v1/settings/business/" && c.method !== "GET")?.body,
      ).toEqual({
        city: "Pimpri",
      }),
    );

    expect(await screen.findByText(/saved: xxxxxx4321/i)).toBeInTheDocument();
    const upi = screen.getByLabelText(/^upi id/i);
    await user.type(upi, "sharma@hdfc");
    await user.click(screen.getByRole("button", { name: /save bank details/i }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.path.includes("bank-details") && c.method !== "GET")?.body,
      ).toEqual({
        upi_id: "sharma@hdfc",
      }),
    );
  });
});

describe("BrandingSettings", () => {
  it("previews the colour while typing and applies it to the app once saved", async () => {
    auth.permissions = ["branding.manage"];
    const branding = {
      display_name: "Sharma Distributors",
      primary_color: "#2f5bea",
      logo_url: null,
      favicon_url: null,
      app_icon_url: null,
    };
    const calls = mockApi({
      "/api/v1/settings/branding/": () => [200, branding],
      "PATCH /api/v1/settings/branding/": (body) => [200, { ...branding, ...(body as object) }],
    });
    renderWithIntl(
      <HostBrandingProvider
        value={{
          hostKind: "TENANT",
          tenantSlug: "sharma",
          branding: { ...branding, slug: "sharma", available: true },
        }}
      >
        <BrandingSettings />
      </HostBrandingProvider>,
    );
    const user = userEvent.setup();
    const hex = await screen.findByLabelText(/colour code/i);
    await user.clear(hex);
    await user.type(hex, "#c2410c");
    const preview = screen.getByRole("img", { name: /preview/i });
    expect(preview.style.getPropertyValue("--primary")).toMatch(/^oklch/);
    expect(document.querySelectorAll("style#brand-theme")).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(document.querySelectorAll("style#brand-theme")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
      display_name: "Sharma Distributors",
      primary_color: "#c2410c",
    });
  });
});

describe("PolicySettings", () => {
  const row = (key: string, group: string, value: unknown, isDefault = true): Setting => ({
    key,
    group,
    type: "bool",
    default: false,
    value,
    is_default: isDefault,
    allowed: [],
    reserved_values: [],
    min_value: null,
    max_value: null,
    pattern: null,
    nullable: false,
    description: "",
    i18n_key: key,
    edit_permission: "settings.manage",
    can_edit: true,
    snapshot_on: [],
    depends_on: null,
    status: "ACTIVE",
  });

  it("shows one group only and resets a value to the rows the server returns", async () => {
    auth.permissions = ["settings.manage"];
    const calls = mockApi({
      "/api/v1/settings/registry/": () => [
        200,
        [row("security.require_staff_2fa", "security", true, false), row("tax.x", "tax", false)],
      ],
      "DELETE /api/v1/settings/values/security.require_staff_2fa/": () => [
        200,
        [row("security.require_staff_2fa", "security", false), row("tax.x", "tax", false)],
      ],
    });
    renderWithIntl(<PolicySettings group="security" />);
    const user = userEvent.setup();
    const toggle = await screen.findByRole("switch");
    expect(toggle).toBeChecked();
    expect(screen.getAllByRole("switch")).toHaveLength(1);
    const card = toggle.closest("[data-slot=card]") as HTMLElement;
    await user.click(within(card).getByRole("button", { name: /reset/i }));
    await waitFor(() => expect(screen.getByRole("switch")).not.toBeChecked());
    expect(calls.some((c) => c.method === "DELETE")).toBe(true);
  });

  // Every settings group has its page title, description and form heading (a missing message
  // throws in the strict test provider, as it would show a raw key to the distributor).
  it.each(POLICY_GROUPS)("renders the %s group with all of its messages", async (group) => {
    auth.permissions = ["settings.manage"];
    mockApi({ "/api/v1/settings/registry/": () => [200, [row(`${group}.x`, group, false)]] });
    renderWithIntl(<PolicySettings group={group} />);
    expect(await screen.findByRole("switch")).toBeInTheDocument();
  });
});
