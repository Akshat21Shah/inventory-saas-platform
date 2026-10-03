/** Jest: the phone's secure storage in memory, and the app's build settings. */
const mockStore = new Map<string, string>();

jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(async (key: string) => mockStore.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockStore.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockStore.delete(key)),
}));

jest.mock("expo-constants", () => ({
  __esModule: true,
  default: {
    expoConfig: {
      name: "Shop",
      version: "1.0.0",
      android: { package: "com.example.shop" },
      extra: {
        apiUrl: "http://api.test",
        platformDomain: "test",
        release: false,
        sentryDsn: "",
        build: 1,
      },
    },
  },
}));

jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "en" }] }));

beforeEach(() => mockStore.clear());

// The phone's connection: NetInfo's own mock (connected).
jest.mock("@react-native-community/netinfo", () =>
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- NetInfo's published mock
  require("@react-native-community/netinfo/jest/netinfo-mock.js"),
);
