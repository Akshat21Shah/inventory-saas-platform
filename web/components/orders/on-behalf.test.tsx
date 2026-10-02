import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { OrderOnBehalfPage } from "./on-behalf";

const params = vi.hoisted(() => ({ value: new URLSearchParams() }));
vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({ me: { id: "u1" }, can: () => true, feature: () => true }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/manage/orders/new",
  useSearchParams: () => params.value,
}));
afterEach(() => vi.unstubAllGlobals());

describe("OrderOnBehalfPage", () => {
  it("opens the shop given in the address (from the shop activity list)", async () => {
    params.value = new URLSearchParams("shop=r1");
    mockApi({
      "/api/v1/retailers/r1/": () => [
        200,
        { id: "r1", shop_name: "Ganesh Kirana", status: "ACTIVE" },
      ],
    });
    renderWithIntl(<OrderOnBehalfPage />);
    expect(await screen.findByText("Ganesh Kirana")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Other shop" })).toBeInTheDocument();
  });

  it("asks for the shop otherwise", async () => {
    params.value = new URLSearchParams();
    mockApi({ "/api/v1/retailers/": () => [200, { next: null, previous: null, results: [] }] });
    renderWithIntl(<OrderOnBehalfPage />);
    expect(await screen.findByRole("heading", { name: "Choose the shop" })).toBeInTheDocument();
  });
});
