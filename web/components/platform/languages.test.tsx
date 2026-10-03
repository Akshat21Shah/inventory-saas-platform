import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { PlatformLanguagesPage } from "./languages";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/platform/languages",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => vi.unstubAllGlobals());

const setting = (key: string, value: string) => ({
  key,
  value,
  default: key.endsWith("enabled") ? "en" : "",
  type: "STRING",
  group: "languages",
  description: "",
  is_default: false,
});
const progress = [
  {
    code: "hi",
    name: "Hindi",
    native: "हिन्दी",
    enabled: false,
    total: 6029,
    translated: 6029,
    reviewed: 120,
    new_suggestions: 1,
  },
  {
    code: "mr",
    name: "Marathi",
    native: "मराठी",
    enabled: false,
    total: 6029,
    translated: 6029,
    reviewed: 0,
    new_suggestions: 0,
  },
];
const suggestion = {
  id: "s1",
  language: "hi",
  screen: "/shop/orders",
  current_text: "बकाया",
  suggestion: "उधार",
  status: "NEW",
  tenant_name: "Sharma Distributors",
  sent_by: "Ganesh Kirana",
  created_at: "2026-10-03T05:00:00Z",
  resolved_by: "",
  resolved_at: null,
};

function api() {
  return mockApi({
    "/api/v1/platform/settings/registry/": () => [
      200,
      [
        setting("platform.languages_enabled", "en"),
        setting("platform.language_test_tenants", "sharma"),
      ],
    ],
    "PATCH /api/v1/platform/settings/": () => [200, []],
    "/api/v1/platform/texts/progress/": () => [200, progress],
    "/api/v1/platform/texts/suggestions/": () => [
      200,
      { next: null, previous: null, results: [suggestion] },
    ],
    "PATCH /api/v1/platform/texts/suggestions/s1/": () => [200, { ...suggestion, status: "DONE" }],
  });
}

describe("Super admin → Languages (ADR-060)", () => {
  it("turns a language on for everyone, warning when its review isn't done", async () => {
    const calls = api();
    renderWithIntl(<PlatformLanguagesPage />);
    const hindi = await screen.findByRole("region", { name: /हिन्दी/ });
    expect(within(hindi).getByText("Off (testing only)")).toBeVisible();
    expect(within(hindi).getByText("120 of 6,029")).toBeVisible();
    const user = userEvent.setup();
    await user.click(within(hindi).getByRole("switch", { name: "Hindi on for everyone" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Only 120 of 6,029 texts have been reviewed");
    await user.click(within(dialog).getByRole("button", { name: "Turn on" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
        values: { "platform.languages_enabled": "en,hi" },
      }),
    );
  });

  it("adds a test distributor and settles a suggested word", async () => {
    const calls = api();
    renderWithIntl(<PlatformLanguagesPage />);
    const testers = await screen.findByRole("region", { name: "Distributors testing languages" });
    expect(within(testers).getByText("sharma")).toBeVisible();
    const user = userEvent.setup();
    await user.type(within(testers).getByLabelText("Web address name"), "Verma");
    await user.click(within(testers).getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
        values: { "platform.language_test_tenants": "sharma,verma" },
      }),
    );
    const words = screen.getByRole("region", { name: "Suggested words" });
    expect((await within(words).findAllByText("उधार")).length).toBeGreaterThan(0);
    await user.click(within(words).getAllByRole("button", { name: "Done" })[0]!);
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/suggestions/s1/"))?.body).toEqual({
        status: "DONE",
      }),
    );
  });
});
