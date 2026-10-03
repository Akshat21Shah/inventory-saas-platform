import { render, screen } from "@testing-library/react-native";
import { Text } from "react-native";
import { IntlProvider } from "use-intl";

import { intlLocale } from "@/lib/shared/i18n-config";

import { messagesFor } from "./messages";
import { useTranslations } from "./translations";

function Count({ seconds }: { seconds: number }) {
  const t = useTranslations("auth.retailer");
  return <Text>{t("resendIn", { seconds })}</Text>;
}

describe.each(["en", "hi", "mr"])("numbers in %s messages", (code) => {
  it("are grouped the Indian way with the digits 0-9", async () => {
    await render(
      <IntlProvider locale={intlLocale(code)} messages={messagesFor(code)} timeZone="Asia/Kolkata">
        <Count seconds={123456} />
      </IntlProvider>,
    );
    expect(screen.getByText(/1,23,456/)).toBeTruthy();
  });
});
