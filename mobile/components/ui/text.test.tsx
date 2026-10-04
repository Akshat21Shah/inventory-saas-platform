import { screen } from "@testing-library/react-native";
import { Platform, StyleSheet } from "react-native";

import { renderScreen } from "@/tests/render";

import { Text } from "./text";

const styleOf = (words: string) => StyleSheet.flatten(screen.getByText(words).props.style);

describe("Text on Android", () => {
  beforeEach(() => jest.replaceProperty(Platform, "OS", "android"));
  afterEach(() => jest.restoreAllMocks());

  it("draws Hindi and Marathi headings in the bundled medium font, without a set line height", async () => {
    await renderScreen(<Text weight="semibold">ऑर्डर हुआ</Text>);
    expect(styleOf("ऑर्डर हुआ")).toMatchObject({ fontFamily: "NotoSansDevanagari-Medium" });
    expect(styleOf("ऑर्डर हुआ").lineHeight).toBeUndefined();
    expect(styleOf("ऑर्डर हुआ").fontWeight).toBeUndefined();
  });

  it("gives regular Devanagari no numeric weight and no set line height", async () => {
    await renderScreen(<Text size="sm">मागच्या वेळी: 2 Pieces</Text>);
    const style = styleOf("मागच्या वेळी: 2 Pieces");
    expect(style.fontWeight).toBeUndefined();
    expect(style.lineHeight).toBeUndefined();
    expect(style.fontFamily).toBeUndefined();
  });

  it("keeps English in the system medium font with the web's line height", async () => {
    await renderScreen(<Text weight="medium">Order placed</Text>);
    expect(styleOf("Order placed")).toMatchObject({
      fontFamily: "sans-serif-medium",
      fontSize: 16,
      lineHeight: 23,
    });
  });

  it("keeps bold as a weight (the phones' bold Devanagari is measured as drawn)", async () => {
    await renderScreen(<Text weight="bold">नमस्ते</Text>);
    expect(styleOf("नमस्ते")).toMatchObject({ fontWeight: "700" });
  });
});
