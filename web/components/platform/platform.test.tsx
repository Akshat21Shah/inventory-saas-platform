import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TenantDetail as Detail } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { PlansPage, TaxMastersPage } from "./masters";
import { OnboardingWizard } from "./onboarding-wizard";
import { TenantDetail } from "./tenant-detail";

const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/platform",
  useSearchParams: () => new URLSearchParams(),
}));

const tenant = (overrides: Partial<Detail> = {}): Detail => ({
  id: "t1",
  name: "Sharma Distributors",
  slug: "sharma",
  status: "ACTIVE",
  gstin: "27AAPFU0939F1ZV",
  state_code: "27",
  city: "Pune",
  plan: { code: "beta", name: "Beta" },
  created_at: "2026-09-01T10:00:00Z",
  legal_name: "Sharma Distributors Pvt Ltd",
  pan: "AAPFU0939F",
  registration_type: "REGULAR",
  address_line1: "1 Market Road",
  address_line2: "",
  pincode: "411001",
  email: "office@sharma.example",
  phone: "9876543210",
  suspended_reason: "",
  suspended_at: null,
  usage: { staff: 2, retailers: 0, pending_invitations: 1 },
  owner: { email: "owner@sharma.example", full_name: "Asha Sharma", status: "JOINED" },
  features: {},
  ...overrides,
});

beforeEach(() => {
  router.push.mockReset();
  router.replace.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("OnboardingWizard", () => {
  function routes() {
    return mockApi({
      "/api/v1/public/states/": () => [200, [{ code: "27", name: "Maharashtra" }]],
      "/api/v1/platform/plans/": () => [200, []],
      "/api/v1/platform/tenants/slug-available/": () => [200, { available: true }],
      "POST /api/v1/platform/tenants/": () => [201, tenant({ id: "new-1", status: "ONBOARDING" })],
    });
  }

  it("will not move on until the step's required fields are filled", async () => {
    routes();
    renderWithIntl(<OnboardingWizard />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^next$/i }));
    expect(screen.getAllByText("This is required.").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText("Company").closest("li")).toHaveAttribute("aria-current", "step");
  });

  it("derives the state from the GSTIN and sends the whole form once on create", async () => {
    const calls = routes();
    renderWithIntl(<OnboardingWizard />);
    const user = userEvent.setup();
    const next = () => user.click(screen.getByRole("button", { name: /^next$/i }));

    await user.type(screen.getByLabelText(/^business name/i), "Sharma Distributors");
    await user.type(screen.getByLabelText(/^legal name/i), "Sharma Distributors Pvt Ltd");
    await user.type(screen.getByLabelText(/^business email/i), "office@sharma.example");
    await user.type(screen.getByLabelText(/^business phone/i), "9876543210");
    await next();
    await user.type(screen.getByLabelText(/^gstin/i), "27aapfu0939f1zv");
    await user.type(screen.getByLabelText(/^address line 1/i), "1 Market Road");
    await user.type(screen.getByLabelText(/^city/i), "Pune");
    await user.type(screen.getByLabelText(/^pin code/i), "411001");
    await next();
    await user.type(screen.getByLabelText(/^owner's email/i), "owner@sharma.example");
    await next();
    expect(screen.getByLabelText(/^web address/i)).toHaveValue("sharma-distributors");
    await next();
    await next();

    const state = screen.getByText("State", { selector: "dt" });
    expect(state.nextElementSibling).toHaveTextContent("27");
    await user.click(screen.getByRole("button", { name: /create distributor/i }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/platform/tenants/new-1"));
    const created = calls.filter((c) => c.method === "POST");
    expect(created).toHaveLength(1);
    expect(created[0]!.body).toMatchObject({
      name: "Sharma Distributors",
      gstin: "27AAPFU0939F1ZV",
      state_code: "27",
      slug: "sharma-distributors",
      owner_email: "owner@sharma.example",
      plan_code: null,
    });
  });
});

describe("TenantDetail", () => {
  it("suspends only with a reason", async () => {
    const calls = mockApi({
      "/api/v1/platform/tenants/t1/": () => [200, tenant()],
      "POST /api/v1/platform/tenants/t1/suspend/": () => [200, tenant({ status: "SUSPENDED" })],
    });
    renderWithIntl(<TenantDetail tenantId="t1" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^suspend$/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^suspend$/i }));
    expect(calls.some((c) => c.path.endsWith("/suspend/"))).toBe(false);
    await user.type(within(dialog).getByLabelText(/reason/i), "Unpaid for 3 months");
    await user.click(within(dialog).getByRole("button", { name: /^suspend$/i }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/suspend/"))?.body).toEqual({
        reason: "Unpaid for 3 months",
      }),
    );
  });

  it("starts a support session and opens the user's business in a new tab", async () => {
    vi.spyOn(window, "location", "get").mockReturnValue({
      ...window.location,
      protocol: "http:",
      hostname: "admin.localhost",
      port: "3000",
    } as Location);
    const tab = { location: { href: "" } };
    const open = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    const calls = mockApi({
      "/api/v1/platform/tenants/t1/": () => [200, tenant()],
      "/api/v1/platform/tenants/t1/users/": () => [
        200,
        {
          next: null,
          previous: null,
          results: [
            {
              id: "m1",
              user: {
                id: "u9",
                email: "clerk@sharma.example",
                full_name: "Ravi Clerk",
                mfa_enabled: false,
                last_login: null,
              },
              role: { code: "sales", name: "Sales" },
              is_active: true,
              joined_at: "2026-09-02T10:00:00Z",
            },
          ],
        },
      ],
      "POST /api/v1/platform/impersonations/": () => [
        201,
        {
          session_id: "s1",
          tenant_slug: "sharma",
          handoff_code: "hand-9",
          target_type: "STAFF",
          expires_at: "2026-09-25T10:30:00Z",
        },
      ],
    });
    renderWithIntl(<TenantDetail tenantId="t1" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: /users/i }));
    await user.click(await screen.findByRole("button", { name: /support session/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/reason/i), "Ticket 42: invoice layout");
    await user.click(within(dialog).getByRole("button", { name: /start session/i }));

    await waitFor(() => expect(tab.location.href).not.toBe(""));
    expect(open).toHaveBeenCalledWith("about:blank", "_blank");
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      tenant_id: "t1",
      user_id: "u9",
      reason: "Ticket 42: invoice layout",
    });
    const target = new URL(tab.location.href);
    expect(target.host).toBe("sharma.localhost:3000");
    expect(target.pathname).toBe("/auth/handoff");
    const fragment = new URLSearchParams(target.hash.slice(1));
    expect(fragment.get("code")).toBe("hand-9");
    expect(fragment.get("next")).toBe("/manage");
  });
});

describe("Masters", () => {
  it("creates a plan with blank limits meaning no limit, and money kept as a string", async () => {
    const calls = mockApi({
      "/api/v1/platform/plans/": () => [200, []],
      "POST /api/v1/platform/plans/": (body) => [201, { id: "p1", ...(body as object) }],
    });
    renderWithIntl(<PlansPage />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /new plan/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/^code/i), "growth");
    await user.type(within(dialog).getByLabelText(/^name/i), "Growth");
    const price = within(dialog).getByLabelText(/^price per month/i);
    await user.clear(price);
    await user.type(price, "1499.50");
    await user.type(within(dialog).getByLabelText(/^max staff/i), "10");
    await user.click(within(dialog).getByRole("button", { name: /create plan/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({
      code: "growth",
      name: "Growth",
      price_monthly: "1499.50",
      max_retailers: null,
      max_staff: 10,
      max_products: null,
      is_default: false,
      is_active: true,
    });
  });

  it("lists every rejected row when an HSN import fails, and imports nothing", async () => {
    mockApi({
      "/api/v1/platform/tax-rates/": () => [200, []],
      "/api/v1/platform/cess-types/": () => [200, []],
      "/api/v1/platform/hsn-rate-hints/": () => [200, { next: null, previous: null, results: [] }],
      "POST /api/v1/platform/hsn-rate-hints/import/": () => [
        400,
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "",
            details: { fields: { file: ["Row 2: bad rate.", "Row 5: bad date."] } },
          },
        },
      ],
    });
    renderWithIntl(<TaxMastersPage />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: /hsn hints/i }));
    const file = new File(["hsn_prefix,gst_rate,effective_from\n"], "hints.csv", {
      type: "text/csv",
    });
    await user.upload(await screen.findByLabelText(/import csv/i, { selector: "input" }), file);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Row 2: bad rate.");
    expect(alert).toHaveTextContent("Row 5: bad date.");
  });
});
