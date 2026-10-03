/**
 * Signing in (ADR-061 item 4), as on the web's main address: mobile number, the 6-digit code,
 * then the distributor when the number has several. The session comes back to the app itself
 * (`client: "app"`). Opened from a link for one distributor, that one is chosen by itself.
 */
import Feather from "@expo/vector-icons/Feather";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useErrorText } from "@/lib/api/error-text";
import {
  authRetailerChooseAccount,
  authRetailerOtpRequest,
  authRetailerOtpVerify,
} from "@/lib/api/generated/endpoints/auth/auth";
import { publicLanguages } from "@/lib/api/generated/endpoints/public/public";
import type { LoginResponse, RetailerAccountChoice } from "@/lib/api/generated/model";
import { useAuth } from "@/lib/auth/auth-provider";
import type { Tokens } from "@/lib/auth/session";
import { currentLanguage, setLanguage } from "@/lib/i18n/language";
import { APP_NAME } from "@/lib/config";
import { useTranslations } from "@/lib/i18n/translations";
import { space, TOUCH, useTheme } from "@/lib/theme/theme";

const TEN_DIGITS = /^[6-9]\d{9}$/;

type Step =
  | { kind: "phone" }
  | { kind: "code" }
  | { kind: "choose"; choiceToken: string; accounts: RetailerAccountChoice[] };

function tokensOf(body: LoginResponse): Tokens | null {
  if (body.status !== "authenticated" || !body.access || !body.refresh || !body.access_expires_at) {
    return null;
  }
  return { access: body.access, refresh: body.refresh, access_expires_at: body.access_expires_at };
}

export function SignIn({ distributor }: { distributor?: string }) {
  const t = useTranslations("auth.retailer");
  const errors = useErrorText();
  const { signIn } = useAuth();
  const { colors } = useTheme();
  const [step, setStep] = useState<Step>({ kind: "phone" });
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [resendIn, setResendIn] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (resendIn <= 0) return;
    const timer = setTimeout(() => setResendIn((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [resendIn]);

  async function finish(body: LoginResponse) {
    const tokens = tokensOf(body);
    if (tokens) {
      await signIn(tokens);
      return;
    }
    if (body.status === "choose_account" && body.choice_token && body.accounts) {
      const wanted = body.accounts.find((account) => account.tenant_slug === distributor);
      if (wanted) {
        await finish((await authRetailerChooseAccount(choice(body.choice_token, wanted))).data);
        return;
      }
      setStep({ kind: "choose", choiceToken: body.choice_token, accounts: body.accounts });
    }
  }

  const choice = (choiceToken: string, account: RetailerAccountChoice) => ({
    choice_token: choiceToken,
    choice_id: account.choice_id,
    client: "app" as const,
  });

  async function run(action: () => Promise<void>, onError?: () => void) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(errors.message(err));
      onError?.();
    } finally {
      setBusy(false);
    }
  }

  const requestCode = () => {
    if (!TEN_DIGITS.test(phone)) {
      setError(t("phoneInvalid"));
      return;
    }
    void run(async () => {
      const response = await authRetailerOtpRequest({ phone });
      setStep({ kind: "code" });
      setCode("");
      setResendIn(response.data.resend_after);
    });
  };

  const verify = () =>
    void run(
      async () => finish((await authRetailerOtpVerify({ phone, code, client: "app" })).data),
      () => setCode(""),
    );

  const errorLine = error ? (
    <Text tone="danger" weight="medium" accessibilityRole="alert">
      {error}
    </Text>
  ) : null;

  return (
    <Screen edges={["top", "bottom"]}>
      <View style={styles.hero}>
        <View style={[styles.logo, { backgroundColor: colors.primary }]}>
          <Feather name="shopping-bag" size={32} color={colors.primaryForeground} />
        </View>
        <Text size="2xl" weight="bold">
          {APP_NAME}
        </Text>
      </View>
      <LanguagePicker />
      <Card>
        <Text size="xl" weight="bold">
          {t("title")}
        </Text>
        {step.kind === "phone" ? (
          <>
            <Text tone="muted">{t("body")}</Text>
            <Input
              label={t("phoneLabel")}
              hint={t("phoneHint")}
              value={phone}
              onChangeText={(value) => setPhone(value.replace(/\D/g, "").slice(-10))}
              keyboardType="phone-pad"
              autoComplete="tel"
              textContentType="telephoneNumber"
              maxLength={14}
              autoFocus
              onSubmitEditing={requestCode}
            />
            {errorLine}
            <Button
              label={t("sendCode")}
              busy={busy}
              disabled={phone.length !== 10}
              onPress={requestCode}
            />
          </>
        ) : step.kind === "code" ? (
          <>
            <Text tone="muted">{t("codeSent", { phone: `+91 ${phone}` })}</Text>
            <Input
              label={t("codeLabel")}
              value={code}
              onChangeText={(value) => setCode(value.replace(/\D/g, "").slice(0, 6))}
              keyboardType="number-pad"
              autoComplete="sms-otp"
              textContentType="oneTimeCode"
              maxLength={6}
              autoFocus
              onSubmitEditing={verify}
            />
            {errorLine}
            <Button label={t("verify")} busy={busy} disabled={code.length !== 6} onPress={verify} />
            <View style={styles.row}>
              <Button
                variant="ghost"
                label={t("changeNumber")}
                onPress={() => {
                  setStep({ kind: "phone" });
                  setError(null);
                }}
              />
              <Button
                variant="ghost"
                label={resendIn > 0 ? t("resendIn", { seconds: resendIn }) : t("resend")}
                disabled={resendIn > 0 || busy}
                onPress={requestCode}
              />
            </View>
          </>
        ) : (
          <>
            <Text tone="muted">{t("chooseDistributor")}</Text>
            {errorLine}
            {step.accounts.map((account) => (
              <Pressable
                key={account.choice_id}
                accessibilityRole="button"
                disabled={busy}
                onPress={() =>
                  void run(async () =>
                    finish(
                      (await authRetailerChooseAccount(choice(step.choiceToken, account))).data,
                    ),
                  )
                }
                style={[styles.choice, { borderColor: colors.border }]}
              >
                <View style={styles.choiceText}>
                  <Text weight="semibold">{account.distributor_name}</Text>
                  <Text tone="muted" size="sm">
                    {account.shop_name}
                  </Text>
                </View>
                <Feather name="chevron-right" size={20} color={colors.mutedForeground} />
              </Pressable>
            ))}
          </>
        )}
      </Card>
    </Screen>
  );
}

/** The languages everyone may use (ADR-060); hidden when only English is on. */
function LanguagePicker() {
  const t = useTranslations("app.signIn");
  const { colors } = useTheme();
  const [selected, setSelected] = useState(currentLanguage());
  const { data } = useQuery({
    queryKey: ["public-languages"],
    queryFn: async () => (await publicLanguages()).data,
  });
  const enabled = (data ?? []).filter((language) => language.enabled);
  useEffect(() => {
    // Before sign-in only the languages on for everyone (the phone's may not be yet).
    if (data && !enabled.some((language) => language.code === selected)) {
      void setLanguage("en").then(() => setSelected("en"));
    }
  }, [data, enabled, selected]);
  if (enabled.length < 2) return null;
  return (
    <View
      style={styles.languages}
      accessibilityRole="radiogroup"
      accessibilityLabel={t("language")}
    >
      {enabled.map((language) => {
        const on = language.code === selected;
        return (
          <Pressable
            key={language.code}
            accessibilityRole="radio"
            accessibilityState={{ selected: on }}
            onPress={() => void setLanguage(language.code).then(() => setSelected(language.code))}
            style={[
              styles.language,
              {
                borderColor: on ? colors.primary : colors.border,
                backgroundColor: on ? colors.brand50 : "transparent",
              },
            ]}
          >
            <Text weight={on ? "semibold" : "normal"}>{language.native}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  hero: { alignItems: "center", gap: space[2], paddingTop: space[6] },
  logo: { width: 64, height: 64, borderRadius: 16, alignItems: "center", justifyContent: "center" },
  row: { flexDirection: "row", justifyContent: "space-between", flexWrap: "wrap" },
  choice: {
    minHeight: TOUCH + 8,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: space[3],
    flexDirection: "row",
    alignItems: "center",
    gap: space[2],
  },
  choiceText: { flex: 1, paddingVertical: space[2] },
  languages: { flexDirection: "row", justifyContent: "center", gap: space[2], flexWrap: "wrap" },
  language: {
    minHeight: TOUCH,
    minWidth: TOUCH,
    paddingHorizontal: space[4],
    borderWidth: 1,
    borderRadius: 999,
    justifyContent: "center",
  },
});
