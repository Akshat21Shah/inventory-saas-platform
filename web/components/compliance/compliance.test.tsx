import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsLayout } from "@/components/distributor/settings-nav";
import type { GstCredentials, Setting } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { ComplianceSettings } from "./settings";

const features = new Set<string>();
const permissions = new Set<string>(["settings.manage"]);
const auth = {
  me: { id: "u1" },
  can: (p: string) => permissions.has(p),
  feature: (f: string) => features.has(f),
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/manage/settings/compliance",
}));

afterEach(() => {
  vi.unstubAllGlobals();
  features.clear();
});

const credentials = (over: Partial<GstCredentials> = {}): GstCredentials => ({
  provider: "mock",
  field_names: ["username", "password", "client_id", "client_secret"],
  required_fields: ["username", "password"],
  environment: "SANDBOX",
  gstin: "27AAKFS1234A1ZM",
  saved: { username: "••••_api", password: "••••word", client_id: "", client_secret: "" },
  status: "VERIFIED",
  verified_at: "2026-09-30T05:00:00Z",
  last_error: "",
  ...over,
});

const band: Setting = {
  key: "compliance.turnover_band",
  group: "compliance",
  type: "enum",
  default: "BELOW_5_CR",
  value: "FROM_5_TO_10_CR",
  is_default: false,
  allowed: ["BELOW_5_CR", "FROM_5_TO_10_CR", "FROM_10_CR"],
  reserved_values: [],
  min_value: null,
  max_value: null,
  pattern: null,
  nullable: false,
  description: "",
  i18n_key: "settings.compliance.turnover_band.description",
  edit_permission: "settings.manage",
  can_edit: true,
  snapshot_on: [],
  depends_on: null,
  status: "ACTIVE",
};

describe("E-invoices & e-way bills settings", () => {
  it("says the modules are off, and asks nothing, while they are off", async () => {
    const calls = mockApi({});
    renderWithIntl(<ComplianceSettings />);
    expect(await screen.findByText("E-invoices and e-way bills aren't switched on")).toBeVisible();
    expect(calls).toEqual([]);
  });

  it("saves the provider login without showing it back, and checks it", async () => {
    features.add("einvoice");
    const user = userEvent.setup();
    const calls = mockApi({
      "/api/v1/settings/gst-credentials/": () => [200, credentials()],
      "PUT /api/v1/settings/gst-credentials/": () => [200, credentials({ status: "CHECKING" })],
      "POST /api/v1/settings/gst-credentials/verify/": () => [
        200,
        credentials({ status: "CHECKING" }),
      ],
      "/api/v1/settings/registry/": () => [200, [band]],
    });
    renderWithIntl(<ComplianceSettings />);
    expect(await screen.findByText("Working")).toBeVisible();
    expect(screen.getByText("Saved: ••••word. Leave blank to keep it.")).toBeVisible();
    expect(screen.getByLabelText(/^Password/)).toHaveValue(""); // never shown back
    await user.type(screen.getByLabelText(/^Password/), "new-secret");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        environment: "SANDBOX",
        values: { password: "new-secret" },
      }),
    );
    await user.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/settings/gst-credentials/verify/")).toBe(true),
    );
    expect(screen.getByText("Annual turnover")).toBeVisible(); // the compliance rules
  });

  it("shows why the provider refused the login", async () => {
    features.add("ewaybill");
    mockApi({
      "/api/v1/settings/gst-credentials/": () => [
        200,
        credentials({ status: "FAILED", last_error: "The provider refused these credentials." }),
      ],
      "/api/v1/settings/registry/": () => [200, []],
    });
    renderWithIntl(<ComplianceSettings />);
    expect(await screen.findByText("The GST provider refused the login:")).toBeVisible();
    expect(screen.getByText("The provider refused these credentials.")).toHaveAttribute(
      "lang",
      "en",
    );
    expect(screen.getByText("Not working")).toBeVisible();
  });

  it("lists the page in Settings only while a module is on", () => {
    const { rerender } = renderWithIntl(
      <SettingsLayout>
        <p>page</p>
      </SettingsLayout>,
    );
    expect(screen.queryByRole("link", { name: "E-invoices & e-way bills" })).toBeNull();
    features.add("ewaybill");
    rerender(
      <SettingsLayout>
        <p>page</p>
      </SettingsLayout>,
    );
    expect(screen.getByRole("link", { name: "E-invoices & e-way bills" })).toBeVisible();
  });
});
