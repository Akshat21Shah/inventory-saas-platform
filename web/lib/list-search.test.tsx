import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useListSearch } from "./list-search";

const url = vi.hoisted(() => ({ params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => url.params }));

describe("useListSearch", () => {
  it("opens with ?q=, keeps what is typed, and follows a later See all", () => {
    url.params = new URLSearchParams("q=parle");
    const { result, rerender } = renderHook(() => useListSearch());
    expect(result.current[0]).toBe("parle");

    act(() => result.current[1]("parle-g"));
    rerender();
    expect(result.current[0]).toBe("parle-g");

    // "See all" again while the list is open: same page, a new ?q=.
    url.params = new URLSearchParams("q=tata");
    rerender();
    expect(result.current[0]).toBe("tata");
  });

  it("starts empty without ?q=", () => {
    url.params = new URLSearchParams();
    const { result } = renderHook(() => useListSearch());
    expect(result.current[0]).toBe("");
  });
});
