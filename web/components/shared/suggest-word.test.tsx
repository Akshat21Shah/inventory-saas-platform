import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { SuggestWordLink } from "./suggest-word";

vi.mock("next/navigation", () => ({ usePathname: () => "/shop/orders" }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

afterEach(() => {
  vi.unstubAllGlobals();
  toast.success.mockReset();
});

describe("Suggest a better word (ADR-060 item 14)", () => {
  it("isn't offered on English screens: English is the source", () => {
    renderWithIntl(<SuggestWordLink />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("sends the screen, its language, the words and the better word", async () => {
    const calls = mockApi({ "POST /api/v1/texts/suggestions/": () => [201, { id: "s1" }] });
    renderWithIntl(<SuggestWordLink />, { locale: "hi" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "बेहतर शब्द सुझाएँ" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("स्क्रीन पर लिखे शब्द"), "बकाया");
    const send = within(dialog).getByRole("button", { name: "भेजें" });
    expect(send).toBeDisabled(); // nothing to send yet
    await user.type(within(dialog).getByLabelText(/बेहतर शब्द/), "उधार");
    await user.click(send);
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        language: "hi",
        screen: "/shop/orders",
        current_text: "बकाया",
        suggestion: "उधार",
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("धन्यवाद! हम इसे देखेंगे।");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
