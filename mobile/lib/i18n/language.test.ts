import * as SecureStore from "expo-secure-store";

import { currentLanguage, loadLanguage, setLanguage } from "./language";

describe("the app's language", () => {
  it("opens in the saved language", async () => {
    await SecureStore.setItemAsync("app.language", "mr");
    expect(await loadLanguage()).toBe("mr");
    expect(currentLanguage()).toBe("mr");
  });

  it("keeps the person's language from the server when the saved one is read after it", async () => {
    await setLanguage("en");
    await SecureStore.setItemAsync("app.language", "en");
    let release: () => void = () => undefined;
    jest
      .mocked(SecureStore.getItemAsync)
      .mockImplementationOnce(() => new Promise((resolve) => (release = () => resolve("en"))));
    const loading = loadLanguage(); // a slow phone: the saved language is still being read
    await setLanguage("hi"); // meanwhile /auth/me answers with Hindi
    release();
    expect(await loading).toBe("hi");
    expect(currentLanguage()).toBe("hi");
    expect(await SecureStore.getItemAsync("app.language")).toBe("hi");
  });
});
