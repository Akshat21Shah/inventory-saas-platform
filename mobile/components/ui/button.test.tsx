import { onlineManager } from "@tanstack/react-query";
import { screen } from "@testing-library/react-native";

import { renderScreen } from "@/tests/render";

import { Button } from "./button";

afterEach(() => onlineManager.setOnline(true));

describe("A button that needs a connection", () => {
  it("is off while the phone is offline, and says why", async () => {
    onlineManager.setOnline(false);
    await renderScreen(<Button label="Place order" needsInternet onPress={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Place order" })).toBeDisabled();
    expect(screen.getByText("Needs internet. Try again when you're back online.")).toBeTruthy();
  });

  it("works as usual when online", async () => {
    await renderScreen(<Button label="Place order" needsInternet onPress={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Place order" })).toBeEnabled();
    expect(screen.queryByText(/Needs internet/)).toBeNull();
  });
});
