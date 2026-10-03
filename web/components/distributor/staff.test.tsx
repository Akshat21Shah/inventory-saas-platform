import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Membership } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { RolesPage, StaffPage } from "./staff";

const auth: {
  me: { id: string; language?: string; languages?: { code: string; native: string }[] };
  can: () => boolean;
} = { me: { id: "u-owner" }, can: () => true };
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));

afterEach(() => vi.unstubAllGlobals());

const member = (id: string, userId: string, name: string, role: string): Membership => ({
  id,
  user: {
    id: userId,
    email: `${name.toLowerCase()}@sharma.example.com`,
    full_name: name,
    mfa_enabled: false,
    last_login: null,
  },
  role: { code: role, name: role },
  is_active: true,
  joined_at: "2026-09-01T10:00:00Z",
});

const roles = [
  {
    id: "r1",
    code: "OWNER",
    name: "Owner",
    is_system: true,
    permissions: ["staff.manage", "orders.view"],
  },
  { id: "r2", code: "SALES", name: "Sales", is_system: true, permissions: ["orders.view"] },
];

function api(extra = {}) {
  return mockApi({
    "/api/v1/roles/": () => [200, roles],
    "/api/v1/staff/": () => [
      200,
      {
        next: null,
        previous: null,
        results: [member("m1", "u-owner", "Asha", "OWNER"), member("m2", "u-2", "Ravi", "SALES")],
      },
    ],
    "/api/v1/staff/invitations/": () => [200, { next: null, previous: null, results: [] }],
    ...extra,
  });
}

describe("StaffPage", () => {
  it("never offers to deactivate yourself", async () => {
    api();
    renderWithIntl(<StaffPage />);
    const ravi = (await screen.findByText("Ravi")).closest("tr")!;
    const asha = screen.getByText("Asha").closest("tr")!;
    expect(within(ravi).getByRole("button", { name: /deactivate/i })).toBeInTheDocument();
    expect(within(asha).queryByRole("button", { name: /deactivate/i })).not.toBeInTheDocument();
  });

  it("invites with a role and shows the server's field error inline", async () => {
    const calls = api({
      "POST /api/v1/staff/invitations/": () => [
        400,
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "",
            details: { fields: { email: ["An invitation is already waiting for this email."] } },
          },
        },
      ],
    });
    renderWithIntl(<StaffPage />);
    const user = userEvent.setup();
    await screen.findByText("Ravi");
    await user.click(screen.getByRole("button", { name: /invite staff/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/^email/i), "new@sharma.example.com");
    await user.click(within(dialog).getByRole("button", { name: /send invitation/i }));
    expect(await within(dialog).findByText(/already waiting/i)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      email: "new@sharma.example.com",
      role_code: "SALES",
    });
  });

  it("sends the invitation in the language the inviter chooses, theirs by default", async () => {
    auth.me = {
      id: "u-owner",
      language: "mr",
      languages: [
        { code: "en", native: "English" },
        { code: "hi", native: "हिन्दी" },
        { code: "mr", native: "मराठी" },
      ],
    };
    const calls = api({ "POST /api/v1/staff/invitations/": () => [201, {}] });
    renderWithIntl(<StaffPage />);
    const user = userEvent.setup();
    await screen.findByText("Ravi");
    await user.click(screen.getByRole("button", { name: /invite staff/i }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("combobox", { name: /language of the invitation/i }),
    ).toHaveTextContent("मराठी");
    await user.type(within(dialog).getByLabelText(/^email/i), "new@sharma.example.com");
    await user.click(within(dialog).getByRole("button", { name: /send invitation/i }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        email: "new@sharma.example.com",
        role_code: "SALES",
        language: "mr",
      }),
    );
    auth.me = { id: "u-owner" };
  });

  it("deactivates after confirmation and sends only the change", async () => {
    const calls = api({
      "PATCH /api/v1/staff/m2/": () => [
        200,
        { ...member("m2", "u-2", "Ravi", "SALES"), is_active: false },
      ],
    });
    renderWithIntl(<StaffPage />);
    const user = userEvent.setup();
    const ravi = (await screen.findByText("Ravi")).closest("tr")!;
    await user.click(within(ravi).getByRole("button", { name: /deactivate/i }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /deactivate/i }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ is_active: false }),
    );
  });
});

describe("RolesPage", () => {
  it("marks each permission per role", async () => {
    api({
      "/api/v1/permissions/": () => [
        200,
        [
          { code: "orders.view", module: "orders", description: "View orders" },
          { code: "staff.manage", module: "staff", description: "Invite staff" },
        ],
      ],
    });
    renderWithIntl(<RolesPage />);
    const row = (await screen.findByText("Invite staff")).closest("tr")!;
    expect(within(row).getAllByLabelText("Allowed")).toHaveLength(1);
    expect(within(row).getAllByLabelText("Not allowed")).toHaveLength(1);
  });
});
