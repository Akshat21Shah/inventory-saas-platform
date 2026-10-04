import { isOlder, parseVersion } from "./version";

describe("app versions", () => {
  it("compares three numbers", () => {
    expect(isOlder("1.1.9", "1.2.0")).toBe(true);
    expect(isOlder("1.10.0", "1.9.0")).toBe(false);
    expect(isOlder("1.2.0", "1.2.0")).toBe(false);
    expect(isOlder("2.0.0", "1.9.9")).toBe(false);
  });

  it("treats an unreadable version as the oldest", () => {
    expect(parseVersion("1.2")).toEqual([0, 0, 0]);
    expect(isOlder("junk", "0.0.1")).toBe(true);
    expect(isOlder("1.0.0", "")).toBe(false); // no minimum
  });
});
