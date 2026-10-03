import { appHref, linkPath } from "./app-href";

describe("Web addresses as the app's screens", () => {
  it("opens an order in Orders, a product, category or search in Catalog", () => {
    expect(appHref("/shop/orders/o1")).toBe("/shop/(tabs)/(orders)/orders/o1");
    expect(appHref("/shop/products/p1")).toBe("/shop/(tabs)/(catalog)/products/p1");
    expect(appHref("/shop/catalog/c1")).toBe("/shop/(tabs)/(catalog)/catalog/c1");
    expect(appHref("/shop/search?q=chawal")).toBe("/shop/(tabs)/(catalog)/search?q=chawal");
    expect(appHref("/shop/notifications")).toBe("/shop/(tabs)/(home)/notifications");
  });

  it("leaves the pages that have one place as they are", () => {
    for (const path of ["/shop", "/shop/invoices/i1", "/shop/payments", "/shop/orders"]) {
      expect(appHref(path)).toBe(path);
    }
  });

  it("reads the path from a distributor's web address or the app's scheme", () => {
    expect(linkPath("https://sharma.example.com/shop/orders/o1")).toBe("/shop/orders/o1");
    expect(linkPath("http://sharma.192-168-0-106.nip.io:3000/shop/login")).toBe("/shop/login");
    expect(linkPath("shopapp://shop/payments/checkout/c1")).toBe("/shop/payments/checkout/c1");
    expect(linkPath("/shop/orders/o1")).toBe("/shop/orders/o1");
  });
});
