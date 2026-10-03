/** Links' query strings are decoded by the fixed decoder (vendor/decode-uri-component, 0.5.0). */
import queryString from "query-string";

it("decodes links, in Devanagari too, and leaves malformed parts as they are", () => {
  expect(queryString.parse("q=%E0%A4%9F%E0%A4%BE%E0%A4%9F%E0%A4%BE&bad=%%%E0%A4")).toEqual({
    q: "टाटा",
    bad: "%%%E0%A4",
  });
});

it("is quick on input crafted to be slow (GHSA-vcc3-ghjq-m6fr)", () => {
  const started = Date.now();
  queryString.parse(`q=${"%".repeat(2000)}${"%E0%A4".repeat(3000)}`);
  expect(Date.now() - started).toBeLessThan(500);
});
