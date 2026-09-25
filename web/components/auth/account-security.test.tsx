import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { AccountSecurity } from "./account-security";

const auth = {
  me: {} as Record<string, unknown>,
  reloadMe: vi.fn(async () => {}),
  signIn: vi.fn(async () => null),
};
vi.mock("./auth-provider", () => ({ useAuth: () => auth }));

function signedInAs(overrides: Record<string, unknown>) {
  auth.me = {
    id: "u1",
    user_type: "PLATFORM",
    email: "root@example.com",
    full_name: "Root",
    preferred_language: "en",
    mfa_enabled: true,
    mfa_required: true,
    impersonation: null,
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  auth.signIn.mockClear();
});

describe("AccountSecurity", () => {
  it("never offers to turn off 2FA when the account requires it", () => {
    signedInAs({});
    renderWithIntl(<AccountSecurity />);
    expect(screen.getByText(/required for your account/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /turn off/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new recovery codes/i })).toBeInTheDocument();
  });

  it("hides password and 2FA changes during a support session", () => {
    signedInAs({ user_type: "STAFF", impersonation: { mode: "READ_ONLY" } });
    renderWithIntl(<AccountSecurity />);
    expect(screen.getByText(/cannot be changed during a support session/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /change password/i })).not.toBeInTheDocument();
  });

  it("keeps this session going with the new tokens after a password change", async () => {
    signedInAs({ user_type: "STAFF", mfa_required: false });
    const calls = mockApi({
      "POST /api/v1/auth/password/change/": () => [
        200,
        { access: "fresh", access_expires_at: "2026-09-25T12:00:00Z" },
      ],
    });
    renderWithIntl(<AccountSecurity />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/^current password/i), "old-password-1");
    await user.type(screen.getByLabelText(/^new password/i), "a-much-better-pass");
    await user.type(screen.getByLabelText(/^confirm new password/i), "a-much-better-pass");
    await user.click(screen.getByRole("button", { name: /change password/i }));
    await waitFor(() => expect(auth.signIn).toHaveBeenCalledWith("fresh", "2026-09-25T12:00:00Z"));
    expect(calls[0]!.body).toEqual({
      current_password: "old-password-1",
      new_password: "a-much-better-pass",
    });
  });
});
