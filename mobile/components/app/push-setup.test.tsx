import { waitFor } from "@testing-library/react-native";

import { renderScreen } from "@/tests/render";

import { PushSetup } from "./push-setup";

const mockPush = jest.fn();
jest.mock("expo-router", () => ({ router: { push: (...a: unknown[]) => mockPush(...a) } }));
jest.mock("@/lib/auth/auth-provider", () => ({
  useAuth: () => ({ me: { tenant: { slug: "sharma" } } }),
}));
const mockMarkRead = jest.fn(async () => ({ status: 204 }));
jest.mock("@/lib/api/generated/endpoints/shop/shop", () => ({
  shopNotificationsMarkRead: (...a: unknown[]) => mockMarkRead(...(a as [])),
}));
jest.mock("@/lib/push/push", () => ({
  followTokenChanges: () => () => undefined,
  foregroundBehaviour: () => ({}),
  loadSoundSetting: jest.fn(async () => true),
  registerThisPhone: jest.fn(async () => undefined),
  setUpChannels: jest.fn(async () => undefined),
}));
let mockResponse: unknown = null;
jest.mock("expo-notifications", () => ({
  DEFAULT_ACTION_IDENTIFIER: "expo.modules.notifications.actions.DEFAULT",
  setNotificationHandler: jest.fn(),
  useLastNotificationResponse: () => mockResponse,
  addNotificationReceivedListener: () => ({ remove: jest.fn() }),
}));

const tapped = (data: Record<string, string>) => ({
  actionIdentifier: "expo.modules.notifications.actions.DEFAULT",
  notification: { request: { identifier: "push-1", content: { data } } },
});

beforeEach(() => {
  mockPush.mockReset();
  mockMarkRead.mockClear();
});

describe("A tapped app notification", () => {
  it("opens its page and marks the message read, as the inbox does", async () => {
    mockResponse = tapped({ path: "/shop/orders/o1", notification: "n1", tenant: "sharma" });
    await renderScreen(<PushSetup />);
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/shop/(tabs)/(orders)/orders/o1"));
    expect(mockMarkRead).toHaveBeenCalledWith("n1");
  });

  it("is left alone when it's from another distributor than the one signed in", async () => {
    mockResponse = tapped({ path: "/shop/orders/o9", notification: "n9", tenant: "gupta" });
    await renderScreen(<PushSetup />);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(mockPush).not.toHaveBeenCalled();
    expect(mockMarkRead).not.toHaveBeenCalled();
  });
});
