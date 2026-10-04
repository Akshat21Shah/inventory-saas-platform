import { fireEvent, screen, waitFor } from "@testing-library/react-native";

import { renderScreen } from "@/tests/render";

import { SignIn } from "./sign-in";

const mockSignIn = jest.fn();
jest.mock("@/lib/auth/auth-provider", () => ({ useAuth: () => ({ signIn: mockSignIn }) }));

const mockAuth = {
  authRetailerOtpRequest: jest.fn(),
  authRetailerOtpVerify: jest.fn(),
  authRetailerChooseAccount: jest.fn(),
};
jest.mock("@/lib/api/generated/endpoints/auth/auth", () => ({
  authRetailerOtpRequest: (...args: unknown[]) => mockAuth.authRetailerOtpRequest(...args),
  authRetailerOtpVerify: (...args: unknown[]) => mockAuth.authRetailerOtpVerify(...args),
  authRetailerChooseAccount: (...args: unknown[]) => mockAuth.authRetailerChooseAccount(...args),
}));
jest.mock("@/lib/api/generated/endpoints/public/public", () => ({
  publicLanguages: async () => ({
    data: [{ code: "en", name: "English", native: "English", enabled: true }],
  }),
}));

const SESSION = {
  status: "authenticated",
  access: "A",
  refresh: "R",
  access_expires_at: "2030-01-01T00:00:00Z",
};
const ACCOUNTS = {
  status: "choose_account",
  choice_token: "C",
  accounts: [
    {
      choice_id: "a",
      distributor_name: "Alpha Traders",
      shop_name: "Ganesh Kirana",
      tenant_slug: "alpha",
    },
    {
      choice_id: "b",
      distributor_name: "Bravo Foods",
      shop_name: "Ganesh Kirana",
      tenant_slug: "bravo",
    },
  ],
};

async function toCode() {
  mockAuth.authRetailerOtpRequest.mockResolvedValue({
    data: { expires_in: 300, resend_after: 30 },
  });
  await fireEvent.changeText(screen.getByLabelText("Mobile number"), "98765 43210");
  await fireEvent.press(screen.getByRole("button", { name: "Send code" }));
  await screen.findByText("We sent a code to +91 9876543210.");
  await fireEvent.changeText(screen.getByLabelText("6-digit code"), "123456");
}

beforeEach(() => jest.clearAllMocks());

it("signs in with the number and the code, the session coming to the app", async () => {
  await renderScreen(<SignIn />);
  await fireEvent.changeText(screen.getByLabelText("Mobile number"), "12345");
  expect(screen.getByRole("button", { name: "Send code" })).toBeDisabled();
  await toCode();
  expect(mockAuth.authRetailerOtpRequest).toHaveBeenCalledWith({ phone: "9876543210" });
  mockAuth.authRetailerOtpVerify.mockResolvedValue({ data: SESSION });
  await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
  await waitFor(() =>
    expect(mockSignIn).toHaveBeenCalledWith({
      access: "A",
      refresh: "R",
      access_expires_at: SESSION.access_expires_at,
    }),
  );
  expect(mockAuth.authRetailerOtpVerify).toHaveBeenCalledWith({
    phone: "9876543210",
    code: "123456",
    client: "app",
  });
});

it("lets a number with several distributors choose one", async () => {
  await renderScreen(<SignIn />);
  await toCode();
  mockAuth.authRetailerOtpVerify.mockResolvedValue({ data: ACCOUNTS });
  mockAuth.authRetailerChooseAccount.mockResolvedValue({ data: SESSION });
  await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
  await fireEvent.press(await screen.findByText("Bravo Foods"));
  await waitFor(() => expect(mockSignIn).toHaveBeenCalled());
  expect(mockAuth.authRetailerChooseAccount).toHaveBeenCalledWith({
    choice_token: "C",
    choice_id: "b",
    client: "app",
  });
});

it("chooses by itself the distributor a link was for", async () => {
  await renderScreen(<SignIn distributor="alpha" />);
  await toCode();
  mockAuth.authRetailerOtpVerify.mockResolvedValue({ data: ACCOUNTS });
  mockAuth.authRetailerChooseAccount.mockResolvedValue({ data: SESSION });
  await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
  await waitFor(() => expect(mockSignIn).toHaveBeenCalled());
  expect(mockAuth.authRetailerChooseAccount).toHaveBeenCalledWith({
    choice_token: "C",
    choice_id: "a",
    client: "app",
  });
  expect(screen.queryByText("Bravo Foods")).toBeNull();
});

it("shows the server's words for a wrong code and clears it", async () => {
  await renderScreen(<SignIn />);
  await toCode();
  const { ApiError } = jest.requireActual("@/lib/shared/errors");
  mockAuth.authRetailerOtpVerify.mockRejectedValue(
    new ApiError(400, { code: "OTP_INVALID", message: "", details: {} }),
  );
  await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.getByLabelText("6-digit code").props.value).toBe("");
});
