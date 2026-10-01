import { describe, expect, it } from "vitest";

import { rank } from "./pages";

describe("rank", () => {
  const words = "dues, outstanding, party ledger, statement";

  it("puts the name first, then a search word as typed, then words spread over them", () => {
    expect(rank("Receivables", words, "receiv")).toBe(4);
    expect(rank("Receivables", words, "Dues")).toBe(3);
    expect(rank("Receivables", words, "party led")).toBe(2);
    expect(rank("Receivables", words, "dues statement")).toBe(1);
  });

  it("is no match without every typed word, or without search words", () => {
    expect(rank("Receivables", words, "dues report")).toBe(0);
    expect(rank("Receivables", "", "dues")).toBe(0);
  });
});
