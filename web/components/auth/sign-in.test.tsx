import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PublicBranding } from "@/lib/api/generated/model";
import { resetSessionForTests } from "@/lib/auth/session";
import type { HostKind } from "@/lib/hosts";
import { renderWithIntl } from "@/tests/render";

import { AuthProvider } from "./auth-provider";
import { LoginScreen } from "./login-screen";
import { HostBrandingProvider } from "./tenant-branding";

const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/login",
}));

type Handler = (body: unknown) => [number, unknown];

function mockApi(routes: Record<string, Handler>) {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const body = init.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, body });
      const path = Object.keys(routes).find((p) => url.endsWith(p));
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

const branding = (available: boolean): PublicBranding => ({
  slug: "sharma",
  display_name: "Sharma Distributors",
  primary_color: "#2f5bea",
  available,
  logo_url: null,
  favicon_url: null,
  app_icon_url: null,
});

function renderLogin(hostKind: HostKind, brand: PublicBranding | null = null) {
  return renderWithIntl(
    <HostBrandingProvider value={{ hostKind, tenantSlug: brand?.slug ?? null, branding: brand }}>
      <AuthProvider>
        <LoginScreen />
      </AuthProvider>
    </HostBrandingProvider>,
  );
}

const me = (userType: string) => ({
  id: "u1",
  user_type: userType,
  email: "owner@example.com",
  phone: null,
  full_name: "Owner",
  preferred_language: "en",
  tenant: null,
  role: null,
  retailer: null,
  permissions: [],
  features: {},
  impersonation: null,
  mfa_enabled: true,
  mfa_required: false,
});
const later = () => new Date(Date.now() + 600_000).toISOString();

describe("LoginScreen", () => {
  beforeEach(() => {
    resetSessionForTests();
    router.replace.mockReset();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows only the neutral message for an unavailable business (ADR-032)", async () => {
    mockApi({});
    renderLogin("TENANT", branding(false));
    expect(
      await screen.findByText(
        "This account is currently unavailable. Please contact your distributor.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/email address/i)).not.toBeInTheDocument();
  });

  it("signs staff in through two-step verification", async () => {
    const calls = mockApi({
      "/api/v1/auth/staff/login/": () => [200, { status: "mfa_required", mfa_token: "mfa-1" }],
      "/api/v1/auth/staff/mfa/verify/": () => [
        200,
        { status: "authenticated", user_type: "STAFF", access: "tok", access_expires_at: later() },
      ],
      "/api/v1/auth/me/": () => [200, me("STAFF")],
    });
    renderLogin("TENANT", branding(true));
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/email address/i), "owner@example.com");
    await user.type(screen.getByLabelText(/^password/i), "a-strong-password");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));
    await user.type(await screen.findByLabelText(/6-digit code/i), "123456");
    await user.click(screen.getByRole("button", { name: /verify/i }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/manage"));
    expect(calls.find((c) => c.url.endsWith("/mfa/verify/"))?.body).toEqual({
      mfa_token: "mfa-1",
      code: "123456",
    });
  });

  it("shows the server's error without revealing which part was wrong", async () => {
    mockApi({
      "/api/v1/auth/staff/login/": () => [
        400,
        { error: { code: "INVALID_CREDENTIALS", message: "x", details: {} } },
      ],
    });
    renderLogin("ADMIN");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/email address/i), "root@example.com");
    await user.type(screen.getByLabelText(/^password/i), "wrong-password");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/email or password is incorrect/i);
  });

  it("lets a shop owner on the generic domain choose a distributor, then moves there", async () => {
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({
      ...window.location,
      protocol: "http:",
      hostname: "localhost",
      port: "3000",
      assign,
    } as Location);
    const calls = mockApi({
      "/api/v1/auth/retailer/otp/request/": () => [202, { expires_in: 300, resend_after: 30 }],
      "/api/v1/auth/retailer/otp/verify/": () => [
        200,
        {
          status: "choose_account",
          choice_token: "choice-1",
          accounts: [
            {
              choice_id: "a1",
              distributor_name: "Sharma Distributors",
              shop_name: "Ganesh Kirana",
            },
            { choice_id: "a2", distributor_name: "Patel Traders", shop_name: "Ganesh Kirana" },
          ],
        },
      ],
      "/api/v1/auth/retailer/choose-account/": () => [
        200,
        { status: "handoff", handoff: { code: "hand-1", tenant_slug: "patel" } },
      ],
    });
    renderLogin("GENERIC");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/mobile number/i), "98765abc43210");
    await user.click(screen.getByRole("button", { name: /send code/i }));
    expect(calls.find((c) => c.url.endsWith("/otp/request/"))?.body).toEqual({
      phone: "9876543210",
    });
    expect(await screen.findByText(/send again in 30s/i)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/6-digit code/i), "654321");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));
    await user.click(await screen.findByRole("button", { name: /patel traders/i }));
    await waitFor(() => expect(assign).toHaveBeenCalledTimes(1));
    const target = new URL(String(assign.mock.calls[0]![0]));
    expect(target.host).toBe("patel.localhost:3000");
    expect(target.pathname).toBe("/auth/handoff");
    expect(new URLSearchParams(target.hash.slice(1)).get("next")).toBe("/shop");
  });

  it("keeps the recovery codes on screen after 2FA set-up until the user confirms", async () => {
    mockApi({
      "/api/v1/auth/staff/login/": () => [
        200,
        { status: "mfa_setup_required", enrolment_token: "e1" },
      ],
      "/api/v1/auth/staff/mfa/enrol/start/": () => [
        200,
        { secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/x?secret=JBSWY3DPEHPK3PXP" },
      ],
      "/api/v1/auth/staff/mfa/enrol/confirm/": () => [
        200,
        {
          status: "authenticated",
          user_type: "PLATFORM",
          access: "tok",
          access_expires_at: later(),
          recovery_codes: ["aaaa-bbbb-cccc-dddd", "eeee-ffff-gggg-hhhh"],
        },
      ],
      "/api/v1/auth/me/": () => [200, me("PLATFORM")],
    });
    renderLogin("ADMIN");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/email address/i), "root@example.com");
    await user.type(screen.getByLabelText(/^password/i), "a-strong-password");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));
    await user.click(await screen.findByRole("button", { name: /set it up now/i }));
    await user.type(await screen.findByLabelText(/6-digit code/i), "123456");
    await user.click(screen.getByRole("button", { name: /confirm and continue/i }));
    expect(await screen.findByText("aaaa-bbbb-cccc-dddd")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled(); // no automatic redirect past the codes
    const proceed = screen.getByRole("button", { name: /^continue$/i });
    expect(proceed).toBeDisabled();
    await user.click(screen.getByLabelText(/saved these codes/i));
    await user.click(proceed);
    expect(router.replace).toHaveBeenCalledWith("/platform");
  });
});
