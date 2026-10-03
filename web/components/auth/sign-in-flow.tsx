"use client";

import { ChevronRight, Copy, KeyRound, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { FormField } from "@/components/shared/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  authStaffMfaEnrolConfirm,
  authStaffMfaEnrolStart,
  authStaffMfaVerify,
} from "@/lib/api/generated/endpoints/auth/auth";
import type {
  LoginResponse,
  MfaSecret,
  RetailerAccountChoice,
  TenantChoice,
} from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { handoffUrl, homeFor, safeNext } from "@/lib/auth/urls";
import { useTranslations } from "@/lib/i18n/translations";

import { useAuth } from "./auth-provider";
import { OtpInput } from "./otp-input";
import { QrCode } from "./qr-code";

export type FlowStep =
  | { kind: "start" }
  | { kind: "mfa"; mfaToken: string }
  | { kind: "enrol"; enrolmentToken: string }
  | { kind: "chooseTenant"; choiceToken: string; tenants: TenantChoice[] }
  | { kind: "chooseAccount"; choiceToken: string; accounts: RetailerAccountChoice[] }
  | { kind: "recoveryCodes"; codes: string[]; destination: string }
  | { kind: "leaving" };

/**
 * Turns any sign-in response into the next step (ADR-020, ADR-025, ADR-029): a session, a move to
 * the tenant's subdomain, a chooser, or a second-factor step. The server decides; the page follows.
 */
export function useSignInFlow({
  next,
  handoffNext,
}: {
  next?: string | null;
  handoffNext: string;
}) {
  const [step, setStep] = useState<FlowStep>({ kind: "start" });
  const { signIn } = useAuth();
  const router = useRouter();

  const apply = useCallback(
    async (response: LoginResponse) => {
      switch (response.status) {
        case "authenticated": {
          const me = await signIn(response.access ?? "", response.access_expires_at);
          const destination = safeNext(next, homeFor(me?.user_type ?? response.user_type));
          if (response.recovery_codes?.length) {
            setStep({ kind: "recoveryCodes", codes: response.recovery_codes, destination });
          } else {
            setStep({ kind: "leaving" });
            router.replace(destination);
          }
          return;
        }
        case "handoff":
          setStep({ kind: "leaving" });
          window.location.assign(
            handoffUrl(response.handoff!.tenant_slug, response.handoff!.code, handoffNext),
          );
          return;
        case "choose_tenant":
          setStep({
            kind: "chooseTenant",
            choiceToken: response.choice_token!,
            tenants: response.tenants ?? [],
          });
          return;
        case "choose_account":
          setStep({
            kind: "chooseAccount",
            choiceToken: response.choice_token!,
            accounts: response.accounts ?? [],
          });
          return;
        case "mfa_required":
          setStep({ kind: "mfa", mfaToken: response.mfa_token! });
          return;
        case "mfa_setup_required":
          setStep({ kind: "enrol", enrolmentToken: response.enrolment_token! });
          return;
      }
    },
    [signIn, next, handoffNext, router],
  );

  const leave = useCallback(
    (destination: string) => {
      setStep({ kind: "leaving" });
      router.replace(destination);
    },
    [router],
  );

  return { step, setStep, apply, leave };
}

function ErrorLine({ text }: { text: string | null }) {
  return text ? (
    <p role="alert" className="text-destructive text-sm font-medium">
      {text}
    </p>
  ) : null;
}

/** Second step when 2FA is on: a code from the app, or a recovery code. */
export function MfaStep({
  mfaToken,
  onResult,
}: {
  mfaToken: string;
  onResult: (response: LoginResponse) => Promise<void>;
}) {
  const t = useTranslations("auth");
  const errors = useErrorText();
  const [useRecovery, setUseRecovery] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = useRecovery
        ? { mfa_token: mfaToken, recovery_code: value }
        : { mfa_token: mfaToken, code: value };
      await onResult((await authStaffMfaVerify(body)).data);
    } catch (err) {
      setError(errors.message(err));
      setValue("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <p className="text-muted-foreground text-sm">
        {useRecovery ? t("mfa.recoveryPrompt") : t("mfa.codePrompt")}
      </p>
      <FormField label={useRecovery ? t("mfa.recoveryLabel") : t("mfa.codeLabel")}>
        {useRecovery ? (
          <Input
            className="h-12 font-mono"
            value={value}
            autoComplete="off"
            onChange={(e) => setValue(e.target.value)}
          />
        ) : (
          <OtpInput value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
        )}
      </FormField>
      <ErrorLine text={error} />
      <Button type="submit" className="min-h-11 w-full" disabled={busy || !value}>
        <ShieldCheck aria-hidden />
        {t("mfa.verify")}
      </Button>
      <Button
        type="button"
        variant="link"
        className="w-full"
        onClick={() => {
          setUseRecovery((v) => !v);
          setValue("");
          setError(null);
        }}
      >
        {useRecovery ? t("mfa.useApp") : t("mfa.useRecovery")}
      </Button>
    </form>
  );
}

/** Set-up at sign-in (mandatory for super admins; staff when the business requires it). */
export function EnrolStep({
  enrolmentToken,
  onResult,
}: {
  enrolmentToken: string;
  onResult: (response: LoginResponse) => Promise<void>;
}) {
  const t = useTranslations("auth");
  const errors = useErrorText();
  const [secret, setSecret] = useState<MfaSecret | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      setSecret((await authStaffMfaEnrolStart({ enrolment_token: enrolmentToken })).data);
    } catch (err) {
      setError(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onResult(
        (await authStaffMfaEnrolConfirm({ enrolment_token: enrolmentToken, code })).data,
      );
    } catch (err) {
      setError(errors.message(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  if (!secret) {
    return (
      <div className="space-y-4">
        <p className="text-muted-foreground text-sm">{t("enrol.intro")}</p>
        <ErrorLine text={error} />
        <Button className="min-h-11 w-full" onClick={() => void start()} disabled={busy}>
          <KeyRound aria-hidden />
          {t("enrol.start")}
        </Button>
      </div>
    );
  }
  return (
    <form onSubmit={confirm} className="space-y-4" noValidate>
      <ol className="text-muted-foreground list-decimal space-y-1 pl-5 text-sm">
        <li>{t("enrol.stepScan")}</li>
        <li>{t("enrol.stepCode")}</li>
      </ol>
      <div className="flex justify-center">
        <QrCode value={secret.otpauth_uri} label={t("enrol.qrLabel")} />
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer">{t("enrol.manual")}</summary>
        <code className="bg-muted mt-2 block rounded p-2 font-mono break-all">{secret.secret}</code>
      </details>
      <FormField label={t("mfa.codeLabel")}>
        <OtpInput value={code} onChange={(e) => setCode(e.target.value)} />
      </FormField>
      <ErrorLine text={error} />
      <Button type="submit" className="min-h-11 w-full" disabled={busy || code.length !== 6}>
        {t("enrol.confirm")}
      </Button>
    </form>
  );
}

/** Shown once after 2FA set-up; the user confirms they saved the codes before continuing. */
export function RecoveryCodesStep({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const t = useTranslations("auth");
  const [saved, setSaved] = useState(false);
  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-sm">{t("recovery.intro")}</p>
      <ul className="bg-muted grid grid-cols-2 gap-2 rounded-lg p-3 font-mono text-sm">
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ul>
      <Button
        variant="outline"
        className="min-h-11 w-full"
        onClick={() => {
          void navigator.clipboard?.writeText(codes.join("\n"));
          toast.success(t("recovery.copied"));
        }}
      >
        <Copy aria-hidden />
        {t("recovery.copy")}
      </Button>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-0.5 size-4"
          checked={saved}
          onChange={(e) => setSaved(e.target.checked)}
        />
        {t("recovery.confirm")}
      </label>
      <Button className="min-h-11 w-full" disabled={!saved} onClick={onDone}>
        {t("recovery.continue")}
      </Button>
    </div>
  );
}

/** A list of large choices (tenants for staff, distributors for retailers). */
export function ChoiceList<T>({
  items,
  getKey,
  render,
  onChoose,
}: {
  items: T[];
  getKey: (item: T) => string;
  render: (item: T) => { title: string; subtitle?: string };
  onChoose: (item: T) => Promise<void>;
}) {
  const errors = useErrorText();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        {items.map((item) => {
          const key = getKey(item);
          const { title, subtitle } = render(item);
          return (
            <li key={key}>
              <button
                type="button"
                disabled={busy !== null}
                onClick={async () => {
                  setBusy(key);
                  setError(null);
                  try {
                    await onChoose(item);
                  } catch (err) {
                    setError(errors.message(err));
                    setBusy(null);
                  }
                }}
                className="hover:border-primary hover:bg-brand-50 flex min-h-14 w-full items-center justify-between gap-3 rounded-xl border p-4 text-left transition-colors disabled:opacity-60"
              >
                <span>
                  <span className="block font-medium">{title}</span>
                  {subtitle ? (
                    <span className="text-muted-foreground block text-sm">{subtitle}</span>
                  ) : null}
                </span>
                <ChevronRight aria-hidden className="text-muted-foreground size-5" />
              </button>
            </li>
          );
        })}
      </ul>
      <ErrorLine text={error} />
    </div>
  );
}
