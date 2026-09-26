import { waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/tests/render";

import { RequireArea } from "./require-area";

const auth = {
  status: "anonymous",
  me: null,
  blockedCode: null,
  signedOut: false,
  signOut: vi.fn(),
};
vi.mock("./auth-provider", () => ({ useAuth: () => auth }));
const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/shop/account" }));

afterEach(() => {
  router.replace.mockReset();
  auth.signedOut = false;
});

describe("RequireArea", () => {
  it("sends a visitor to sign in and back to the page they asked for", async () => {
    renderWithIntl(<RequireArea area="shop">content</RequireArea>);
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/shop/login?next=%2Fshop%2Faccount"),
    );
  });

  it("after signing out, the next sign-in starts from the shop home page", async () => {
    auth.signedOut = true;
    renderWithIntl(<RequireArea area="shop">content</RequireArea>);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/shop/login"));
  });
});
