"use client";

import { KeyRound, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { FormField } from "@/components/shared/form-field";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  authMeUpdate,
  authMfaConfirm,
  authMfaDisable,
  authMfaRecoveryCodes,
  authMfaSetup,
  authPasswordChange,
} from "@/lib/api/generated/endpoints/auth/auth";
import type { MfaSetupResponse, PreferredLanguageEnum } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";

import { useAuth } from "./auth-provider";
import { OtpInput } from "./otp-input";
import { PasswordStrength } from "./password-strength";
import { QrCode } from "./qr-code";
import { RecoveryCodesStep } from "./sign-in-flow";

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2 className="text-lg">{title}</h2>
        </CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function Profile() {
  const t = useTranslations("account");
  const { me, reloadMe } = useAuth();
  const errors = useErrorText();
  const [name, setName] = useState(me?.full_name ?? "");
  const [language, setLanguage] = useState<string>(me?.preferred_language ?? "en");
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await authMeUpdate({
        full_name: name,
        preferred_language: language as PreferredLanguageEnum,
      });
      await reloadMe();
      toast.success(t("saved"));
    } catch (err) {
      toast.error(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title={t("profile")}>
      <form onSubmit={save} className="grid gap-4 sm:grid-cols-2">
        <FormField label={t("fullName")}>
          <Input className="h-10" value={name} onChange={(e) => setName(e.target.value)} />
        </FormField>
        <FormField label={t("language")}>
          <Select value={language} onValueChange={setLanguage}>
            <SelectTrigger className="min-h-10 w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(["en", "hi", "mr"] as const).map((code) => (
                <SelectItem key={code} value={code}>
                  {t(`languages.${code}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <p className="text-muted-foreground text-sm sm:col-span-2">
          {t("email")}: {me?.email ?? me?.phone ?? "—"}
        </p>
        <div className="sm:col-span-2">
          <Button type="submit" disabled={busy} className="min-h-10">
            {t("save")}
          </Button>
        </div>
      </form>
    </Section>
  );
}

function PasswordChange() {
  const t = useTranslations("account");
  const { signIn } = useAuth();
  const errors = useErrorText();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (next !== confirm) {
      setFieldErrors({ confirm: t("passwordMismatch") });
      return;
    }
    setBusy(true);
    setFieldErrors({});
    try {
      const response = await authPasswordChange({ current_password: current, new_password: next });
      // Every other session ends; this one continues with the fresh tokens (ADR-025).
      await signIn(response.data.access, response.data.access_expires_at);
      setCurrent("");
      setNext("");
      setConfirm("");
      toast.success(t("passwordChanged"));
    } catch (err) {
      const fields = errors.fields(err);
      setFieldErrors(fields);
      if (Object.keys(fields).length === 0) toast.error(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title={t("password")} description={t("passwordBody")}>
      <form onSubmit={save} className="grid max-w-md gap-4" noValidate>
        <FormField label={t("currentPassword")} error={fieldErrors.current_password}>
          <Input
            type="password"
            autoComplete="current-password"
            className="h-10"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </FormField>
        <FormField label={t("newPassword")} error={fieldErrors.new_password}>
          <Input
            type="password"
            autoComplete="new-password"
            className="h-10"
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
        </FormField>
        <PasswordStrength password={next} />
        <FormField label={t("confirmPassword")} error={fieldErrors.confirm}>
          <Input
            type="password"
            autoComplete="new-password"
            className="h-10"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </FormField>
        <div>
          <Button type="submit" disabled={busy || !current || !next} className="min-h-10">
            {t("changePassword")}
          </Button>
        </div>
      </form>
    </Section>
  );
}

/** Password plus a current code (or a recovery code) before sensitive 2FA changes. */
function ReauthForm({
  submitLabel,
  destructive,
  onSubmit,
  onCancel,
}: {
  submitLabel: string;
  destructive?: boolean;
  onSubmit: (body: { password: string; code?: string; recovery_code?: string }) => Promise<void>;
  onCancel: () => void;
}) {
  const t = useTranslations("account");
  const errors = useErrorText();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit(
        useRecovery ? { password, recovery_code: code.trim() } : { password, code: code.trim() },
      );
    } catch (err) {
      setError(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid max-w-md gap-4" noValidate>
      <FormField label={t("currentPassword")}>
        <Input
          type="password"
          autoComplete="current-password"
          className="h-10"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </FormField>
      <FormField label={useRecovery ? t("recoveryCode") : t("code")}>
        {useRecovery ? (
          <Input
            className="h-10 font-mono"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        ) : (
          <OtpInput value={code} onChange={(e) => setCode(e.target.value)} />
        )}
      </FormField>
      <button
        type="button"
        className="text-primary justify-self-start text-sm underline-offset-4 hover:underline"
        onClick={() => {
          setUseRecovery((v) => !v);
          setCode("");
        }}
      >
        {useRecovery ? t("useAppCode") : t("useRecoveryCode")}
      </button>
      {error ? (
        <p role="alert" className="text-destructive text-sm font-medium">
          {error}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          {t("cancel")}
        </Button>
        <Button
          type="submit"
          variant={destructive ? "destructive" : "default"}
          disabled={busy || !password || !code}
          className="min-h-10"
        >
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

function TwoStep() {
  const t = useTranslations("account");
  const { me, reloadMe } = useAuth();
  const errors = useErrorText();
  const [mode, setMode] = useState<"idle" | "setup" | "codes" | "disable">("idle");
  const [setup, setSetup] = useState<MfaSetupResponse | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const enabled = Boolean(me?.mfa_enabled);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      setSetup((await authMfaSetup()).data);
      setMode("setup");
    } catch (err) {
      toast.error(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event: FormEvent) {
    event.preventDefault();
    if (!setup) return;
    setBusy(true);
    setError(null);
    try {
      const response = await authMfaConfirm({ setup_token: setup.setup_token, code });
      setCodes(response.data.recovery_codes);
      setSetup(null);
      setCode("");
      setMode("idle");
    } catch (err) {
      setError(errors.message(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  let body: ReactNode;
  if (codes) {
    body = (
      <div className="max-w-md">
        <RecoveryCodesStep
          codes={codes}
          onDone={() => {
            setCodes(null);
            void reloadMe();
          }}
        />
      </div>
    );
  } else if (mode === "setup" && setup) {
    body = (
      <form onSubmit={confirm} className="grid max-w-md gap-4" noValidate>
        <ol className="text-muted-foreground list-decimal space-y-1 pl-5 text-sm">
          <li>{t("stepScan")}</li>
          <li>{t("stepCode")}</li>
        </ol>
        <QrCode value={setup.otpauth_uri} label={t("qrLabel")} />
        <details className="text-sm">
          <summary className="cursor-pointer">{t("manualKey")}</summary>
          <code className="bg-muted mt-2 block rounded p-2 font-mono break-all">
            {setup.secret}
          </code>
        </details>
        <FormField label={t("code")}>
          <OtpInput value={code} onChange={(e) => setCode(e.target.value)} />
        </FormField>
        {error ? (
          <p role="alert" className="text-destructive text-sm font-medium">
            {error}
          </p>
        ) : null}
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={() => setMode("idle")}>
            {t("cancel")}
          </Button>
          <Button type="submit" disabled={busy || code.length !== 6} className="min-h-10">
            {t("turnOn")}
          </Button>
        </div>
      </form>
    );
  } else if (mode === "codes") {
    body = (
      <ReauthForm
        submitLabel={t("newCodes")}
        onCancel={() => setMode("idle")}
        onSubmit={async (reauth) => {
          setCodes((await authMfaRecoveryCodes(reauth)).data.recovery_codes);
          setMode("idle");
        }}
      />
    );
  } else if (mode === "disable") {
    body = (
      <ReauthForm
        destructive
        submitLabel={t("turnOff")}
        onCancel={() => setMode("idle")}
        onSubmit={async (reauth) => {
          await authMfaDisable(reauth);
          toast.success(t("turnedOff"));
          setMode("idle");
          await reloadMe();
        }}
      />
    );
  } else if (enabled) {
    body = (
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" className="min-h-10" onClick={() => setMode("codes")}>
          <KeyRound aria-hidden />
          {t("newCodes")}
        </Button>
        {me?.mfa_required ? (
          <p className="text-muted-foreground self-center text-sm">{t("requiredNote")}</p>
        ) : (
          <Button variant="outline" className="min-h-10" onClick={() => setMode("disable")}>
            {t("turnOff")}
          </Button>
        )}
      </div>
    );
  } else {
    body = (
      <Button className="min-h-10" onClick={() => void start()} disabled={busy}>
        <ShieldCheck aria-hidden />
        {t("setUp")}
      </Button>
    );
  }

  return (
    <Section title={t("twoStep")} description={t("twoStepBody")}>
      <div className="mb-4">
        <Badge variant={enabled ? "default" : "secondary"}>{enabled ? t("on") : t("off")}</Badge>
      </div>
      {body}
    </Section>
  );
}

/** "My account": profile, password and two-step verification (staff and super admins). */
export function AccountSecurity() {
  const t = useTranslations("account");
  const { me } = useAuth();
  const staff = me?.user_type === "STAFF" || me?.user_type === "PLATFORM";
  // Password and 2FA are never changeable during a support session (ADR-029); the server
  // refuses too.
  const supportSession = Boolean(me?.impersonation);
  return (
    <>
      <PageHeader title={t("title")} description={t("body")} />
      <div className="space-y-6">
        <Profile />
        {supportSession ? (
          <p className="bg-warning/15 rounded-lg p-3 text-sm">{t("blockedInSupport")}</p>
        ) : null}
        {staff && !supportSession ? <PasswordChange /> : null}
        {staff && !supportSession ? <TwoStep /> : null}
      </div>
    </>
  );
}
