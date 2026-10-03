import { attemptFor, finishAttempt, pendingAttempt } from "./checkout";

describe("checkout attempts", () => {
  it("keep one key per cart until the order is placed", async () => {
    const first = await attemptFor("user-1", "p1:2|addr|");
    expect(first.key).toMatch(/^[0-9a-f]{32}$/);
    expect((await attemptFor("user-1", "p1:2|addr|")).key).toBe(first.key); // a retry: same key
    expect((await pendingAttempt("user-1"))?.key).toBe(first.key); // survives a restart
    const changed = await attemptFor("user-1", "p1:3|addr|");
    expect(changed.key).not.toBe(first.key); // a changed cart: a new attempt
    await finishAttempt("user-1");
    expect(await pendingAttempt("user-1")).toBeNull();
  });
});
