"use client";

import { ArrowLeft, MessageSquare } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState, type FormEvent } from "react";

import { FormField } from "@/components/shared/form-field";
import { Button } from "@/components/ui/button";
import {
  authRetailerChooseAccount,
  authRetailerOtpRequest,
  authRetailerOtpVerify,
} from "@/lib/api/generated/endpoints/auth/auth";
import { useErrorText } from "@/lib/api/use-error-text";

import { OtpInput } from "./otp-input";
import { PhoneInput } from "./phone-input";
import { ChoiceList, useSignInFlow } from "./sign-in-flow";

const TEN_DIGITS = /^[6-9]\d{9}$/;

/** Mobile number + one-time code for shop owners (ADR-015). Plain words, large targets. */
export function RetailerSignIn() {
  const t = useTranslations("auth.retailer");
  const errors = useErrorText();
  const params = useSearchParams();
  const flow = useSignInFlow({ next: params.get("next"), handoffNext: "/shop" });
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [resendIn, setResendIn] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (resendIn <= 0) return;
    const timer = window.setTimeout(() => setResendIn((s) => s - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [resendIn]);

  async function requestCode(event?: FormEvent) {
    event?.preventDefault();
    if (!TEN_DIGITS.test(phone)) {
      setError(t("phoneInvalid"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await authRetailerOtpRequest({ phone });
      setSent(true);
      setCode("");
      setResendIn(response.data.resend_after);
    } catch (err) {
      setError(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  async function verify(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await flow.apply((await authRetailerOtpVerify({ phone, code })).data);
    } catch (err) {
      setError(errors.message(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  const { step } = flow;
  if (step.kind === "chooseAccount") {
    return (
      <div className="space-y-3">
        <p className="text-muted-foreground">{t("chooseDistributor")}</p>
        <ChoiceList
          items={step.accounts}
          getKey={(account) => account.choice_id}
          render={(account) => ({ title: account.distributor_name, subtitle: account.shop_name })}
          onChoose={async (account) =>
            flow.apply(
              (
                await authRetailerChooseAccount({
                  choice_token: step.choiceToken,
                  choice_id: account.choice_id,
                })
              ).data,
            )
          }
        />
      </div>
    );
  }

  const errorLine = error ? (
    <p role="alert" className="text-destructive text-base font-medium">
      {error}
    </p>
  ) : null;

  if (!sent) {
    return (
      <form onSubmit={requestCode} className="space-y-4" noValidate>
        <FormField label={t("phoneLabel")} hint={t("phoneHint")}>
          <PhoneInput value={phone} onChange={(e) => setPhone(e.target.value)} autoFocus />
        </FormField>
        {errorLine}
        <Button
          type="submit"
          className="min-h-14 w-full text-base"
          disabled={busy || phone.length !== 10}
        >
          <MessageSquare aria-hidden />
          {t("sendCode")}
        </Button>
      </form>
    );
  }

  return (
    <form onSubmit={verify} className="space-y-4" noValidate>
      <p className="text-muted-foreground">{t("codeSent", { phone: `+91 ${phone}` })}</p>
      <FormField label={t("codeLabel")}>
        <OtpInput value={code} onChange={(e) => setCode(e.target.value)} autoFocus />
      </FormField>
      {errorLine}
      <Button
        type="submit"
        className="min-h-14 w-full text-base"
        disabled={busy || code.length !== 6}
      >
        {t("verify")}
      </Button>
      <div className="flex items-center justify-between gap-2">
        <Button
          type="button"
          variant="ghost"
          className="min-h-11"
          onClick={() => {
            setSent(false);
            setError(null);
          }}
        >
          <ArrowLeft aria-hidden />
          {t("changeNumber")}
        </Button>
        <Button
          type="button"
          variant="link"
          className="min-h-11"
          disabled={resendIn > 0 || busy}
          onClick={() => void requestCode()}
        >
          {resendIn > 0 ? t("resendIn", { seconds: resendIn }) : t("resend")}
        </Button>
      </div>
    </form>
  );
}
