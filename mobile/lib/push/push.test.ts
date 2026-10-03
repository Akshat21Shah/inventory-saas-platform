import * as Notifications from "expo-notifications";

const mockRegister = jest.fn();
const mockRemove = jest.fn();
jest.mock("@/lib/api/generated/endpoints/shop/shop", () => ({
  shopDeviceRegister: (...args: unknown[]) => mockRegister(...args),
  shopDeviceRemove: (...args: unknown[]) => mockRemove(...args),
}));
const mockConfig = { push: true };
jest.mock("@/lib/config", () => ({
  APP_VERSION: "1.0.0",
  get config() {
    return mockConfig;
  },
}));
jest.mock("expo-notifications", () => ({
  AndroidImportance: { DEFAULT: 3, HIGH: 4 },
  setNotificationChannelAsync: jest.fn(async () => null),
  getPermissionsAsync: jest.fn(),
  requestPermissionsAsync: jest.fn(),
  getDevicePushTokenAsync: jest.fn(async () => ({ type: "android", data: "fcm-token-1" })),
  addPushTokenListener: jest.fn(() => ({ remove: jest.fn() })),
}));

// eslint-disable-next-line import/first -- after the mocks
import {
  forgetThisPhone,
  foregroundBehaviour,
  loadSoundSetting,
  registerThisPhone,
  setSoundSetting,
  setUpChannels,
} from "./push";

const N = jest.mocked(Notifications);

beforeEach(() => {
  mockConfig.push = true;
  mockRegister.mockReset().mockResolvedValue({ status: 201 });
  mockRemove.mockReset().mockResolvedValue({ status: 204 });
  jest.clearAllMocks();
});

describe("Push on the phone", () => {
  it("makes the three kinds the shop can silence separately, in its language", async () => {
    await setUpChannels({
      orders: "ऑर्डर और डिलीवरी",
      money: "बिल और भुगतान",
      offers: "ऑफ़र और घोषणाएँ",
    });
    const made = N.setNotificationChannelAsync.mock.calls.map(([id, input]) => [
      id,
      input.name,
      input.importance,
      input.sound,
    ]);
    expect(made).toEqual([
      ["orders", "ऑर्डर और डिलीवरी", 4, "default"],
      ["money", "बिल और भुगतान", 4, "default"],
      ["offers", "ऑफ़र और घोषणाएँ", 3, "default"],
    ]);
  });

  it("plays the short sound while the app is open only with the switch on", async () => {
    await loadSoundSetting();
    expect(foregroundBehaviour()).toMatchObject({ shouldPlaySound: true, shouldShowList: true });
    await setSoundSetting(false);
    expect(foregroundBehaviour()).toMatchObject({
      shouldPlaySound: false,
      shouldShowBanner: false,
      shouldShowList: true, // still in the phone's list, silently
    });
    await loadSoundSetting(); // remembered
    expect(foregroundBehaviour().shouldPlaySound).toBe(false);
  });

  it("registers this phone after the shop allows notifications, and forgets it at sign-out", async () => {
    N.getPermissionsAsync.mockResolvedValue({ status: "undetermined" } as never);
    N.requestPermissionsAsync.mockResolvedValue({ status: "granted" } as never);
    await registerThisPhone();
    expect(mockRegister).toHaveBeenCalledWith({
      token: "fcm-token-1",
      platform: "ANDROID",
      app_version: "1.0.0",
    });
    await forgetThisPhone();
    expect(mockRemove).toHaveBeenCalledWith({ token: "fcm-token-1" });
  });

  it("does nothing when the shop says no, or the build has no Firebase", async () => {
    N.getPermissionsAsync.mockResolvedValue({ status: "denied" } as never);
    N.requestPermissionsAsync.mockResolvedValue({ status: "denied" } as never);
    await registerThisPhone();
    mockConfig.push = false;
    await registerThisPhone();
    expect(mockRegister).not.toHaveBeenCalled();
    expect(N.getDevicePushTokenAsync).not.toHaveBeenCalled();
  });
});
