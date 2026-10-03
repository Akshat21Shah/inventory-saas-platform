import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PublicBranding } from "@/lib/api/generated/model";
import { resetSessionForTests } from "@/lib/auth/session";
import type { HostKind } from "@/lib/hosts";
import { renderWithIntl } from "@/tests/render";

import { AuthProvider } from "./auth-provider";
import { InviteScreen } from "./invite-screen";
import { LoginScreen, ShopLoginScreen } from "./login-screen";
import { HostBrandingProvider } from "./tenant-branding";

const router = { replace: vi.fn(), push: vi.fn(), refresh: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/login",
}));

type Handler = (body: unknown) => [number, unknown];

function mockApi(routes: Record<string, Handler>) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const body = init.body ? JSON.parse(String(init.body)) : undefined;
      const method = (init.method ?? "GET").toUpperCase();
      calls.push({ url, method, body });
      const path = Object.keys(routes).find((p) => url.split("?")[0]!.endsWith(p));
      const [status, payload] = path
        ? routes[path]!(body)
        : [401, { error: { code: "NOT_AUTHENTICATED", message: "", details: {} } }];
      return new Response(payload === undefined ? null : JSON.stringify(payload), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

const LANGUAGES = [
  { code: "en", name: "English", native: "English" },
  { code: "hi", name: "Hindi", native: "हिन्दी" },
  { code: "mr", name: "Marathi", native: "मराठी" },
];

const branding = (extra: Partial<PublicBranding> = {}): PublicBranding => ({
  slug: "sharma",
  display_name: "Sharma Distributors",
  primary_color: "#2f5bea",
  available: true,
  logo_url: null,
  favicon_url: null,
  app_icon_url: null,
  languages: LANGUAGES,
  default_language: "en",
  ...extra,
});

function withHost(ui: React.ReactElement, hostKind: HostKind, brand: PublicBranding | null) {
  return (
    <HostBrandingProvider value={{ hostKind, tenantSlug: brand?.slug ?? null, branding: brand }}>
      <AuthProvider>{ui}</AuthProvider>
    </HostBrandingProvider>
  );
}

const later = () => new Date(Date.now() + 600_000).toISOString();

function clearLanguage() {
  document.cookie = "NEXT_LOCALE=; path=/; max-age=0";
  sessionStorage.clear();
}

describe("Choosing a language before signing in (ADR-060)", () => {
  beforeEach(() => {
    resetSessionForTests();
    clearLanguage();
    router.refresh.mockReset();
    router.replace.mockReset();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    clearLanguage();
  });

  it("offers the distributor's languages and saves the pick to the profile at sign-in", async () => {
    const calls = mockApi({
      "/api/v1/auth/staff/login/": () => [200, { status: "mfa_required", mfa_token: "m" }],
      "/api/v1/auth/staff/mfa/verify/": () => [
        200,
        { status: "authenticated", user_type: "STAFF", access: "tok", access_expires_at: later() },
      ],
      "/api/v1/auth/me/": () => [
        200,
        {
          id: "u1",
          user_type: "STAFF",
          email: "o@example.com",
          full_name: "Owner",
          language: "en",
          languages: LANGUAGES,
          permissions: [],
          features: {},
        },
      ],
    });
    renderWithIntl(withHost(<LoginScreen />, "TENANT", branding()));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("combobox", { name: "Language" }));
    await user.click(await screen.findByRole("option", { name: "हिन्दी" }));
    expect(document.cookie).toContain("NEXT_LOCALE=hi");
    expect(router.refresh).toHaveBeenCalled();

    await user.type(screen.getByLabelText(/email address/i), "o@example.com");
    await user.type(screen.getByLabelText(/^password/i), "a-strong-password");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));
    await user.type(await screen.findByLabelText(/6-digit code/i), "123456");
    await user.click(screen.getByRole("button", { name: /verify/i }));
    await waitFor(() =>
      expect(calls.find((c) => c.url.endsWith("/auth/me/") && c.method === "PATCH")?.body).toEqual({
        preferred_language: "hi",
      }),
    );
  });

  it("opens a shop's sign-in in the distributor's language for shops until someone picks", async () => {
    mockApi({});
    renderWithIntl(withHost(<ShopLoginScreen />, "TENANT", branding({ default_language: "mr" })));
    await waitFor(() => expect(document.cookie).toContain("NEXT_LOCALE=mr"));
    expect(router.refresh).toHaveBeenCalled();
  });

  it("offers nothing to choose when only English is on", async () => {
    mockApi({});
    renderWithIntl(withHost(<LoginScreen />, "TENANT", branding({ languages: [LANGUAGES[0]!] })));
    expect(await screen.findByLabelText(/email address/i)).toBeVisible();
    expect(screen.queryByRole("combobox", { name: "Language" })).toBeNull();
  });

  it("opens an invitation in its language and gives the new account the page's", async () => {
    const calls = mockApi({
      "/api/v1/auth/invitations/preview/": () => [
        200,
        {
          tenant_name: "Sharma Distributors",
          email: "new@example.com",
          role: { code: "SALES", name: "Sales" },
          invited_by: "Owner",
          existing_account: false,
          expires_at: later(),
          language: "mr",
        },
      ],
      "/api/v1/auth/invitations/accept/": () => [
        400,
        { error: { code: "X", message: "x", details: {} } },
      ],
    });
    renderWithIntl(withHost(<InviteScreen token="t1" />, "TENANT", branding()), {
      locale: "mr",
    });
    await waitFor(() => expect(document.cookie).toContain("NEXT_LOCALE=mr"));
    const user = userEvent.setup();
    const name = await screen.findByRole("textbox", { name: /नाव/ });
    await user.type(name, "Meera");
    const password = document.querySelector<HTMLInputElement>("input[type=password]")!;
    await user.type(password, "a-new-strong-passphrase");
    await user.click(screen.getByRole("button", { name: /स्वीकार/ }));
    await waitFor(() =>
      expect(calls.find((c) => c.url.endsWith("/accept/"))?.body).toMatchObject({
        token: "t1",
        language: "mr",
      }),
    );
  });
});
