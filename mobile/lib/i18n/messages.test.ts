/** The app's own texts (`messages/app`): every language has every key with the same placeholders. */
import en from "@/messages/app/en.json";
import hi from "@/messages/app/hi.json";
import mr from "@/messages/app/mr.json";

type Tree = { [key: string]: string | Tree };

function flatten(tree: Tree, prefix = ""): Record<string, string> {
  return Object.entries(tree).reduce<Record<string, string>>((out, [key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof value === "string"
      ? { ...out, [path]: value }
      : { ...out, ...flatten(value, path) };
  }, {});
}

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)/g)].map((m) => m[1]).sort();

describe.each([
  ["hi", hi],
  ["mr", mr],
])("the app's %s texts", (_code, own) => {
  const english = flatten(en as Tree);
  const translated = flatten(own as Tree);

  it("have every English key and no other", () => {
    expect(Object.keys(translated).sort()).toEqual(Object.keys(english).sort());
  });

  it("keep the placeholders", () => {
    for (const [key, text] of Object.entries(english)) {
      expect([key, placeholders(translated[key] ?? "")]).toEqual([key, placeholders(text)]);
    }
  });
});
