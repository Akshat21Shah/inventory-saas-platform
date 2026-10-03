"use client";

import { UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState, type FormEvent } from "react";

import { FormField } from "@/components/shared/form-field";
import { PageSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  authInvitationAccept,
  authInvitationPreview,
} from "@/lib/api/generated/endpoints/auth/auth";
import type { InvitationPreview } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { pickedLanguage, rememberLanguage } from "@/lib/i18n/client";
import { languageOf } from "@/lib/i18n/config";

import { AuthCard } from "./auth-card";
import { PasswordStrength } from "./password-strength";
import { EnrolStep, MfaStep, RecoveryCodesStep, useSignInFlow } from "./sign-in-flow";

/** /invite/<token> on the tenant's subdomain. Works while the business is still being set up:
 * the owner accepting is what activates it (ADR-030). */
export function InviteScreen({ token }: { token: string }) {
  const t = useTranslations("auth");
  const errors = useErrorText();
  const flow = useSignInFlow({ next: "/manage", handoffNext: "/manage" });
  const router = useRouter();
  const locale = useLocale();
  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    authInvitationPreview({ token })
      .then((response) => {
        setPreview(response.data);
        // The page opens in the invitation's language, unless the person picked another.
        if (!pickedLanguage() && rememberLanguage(response.data.language)) router.refresh();
      })
      .catch((err: unknown) => setLoadError(errors.message(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once per token
  }, [token]);

  async function accept(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setFieldErrors({});
    try {
      // A new account keeps the language this page is shown in.
      const language = languageOf(locale);
      await flow.apply(
        (await authInvitationAccept({ token, full_name: fullName, password, language })).data,
      );
    } catch (err) {
      setFieldErrors(errors.fields(err));
      setError(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <AuthCard title={t("invite.invalidTitle")}>
        <p role="alert" className="text-muted-foreground">
          {loadError}
        </p>
        <Link href="/login" className="text-primary hover:underline">
          {t("backToSignIn")}
        </Link>
      </AuthCard>
    );
  }
  if (!preview) return <PageSkeleton />;
  const { step } = flow;
  if (step.kind === "mfa")
    return (
      <AuthCard title={t("mfa.title")}>
        <MfaStep mfaToken={step.mfaToken} onResult={flow.apply} />
      </AuthCard>
    );
  if (step.kind === "enrol")
    return (
      <AuthCard title={t("enrol.title")}>
        <EnrolStep enrolmentToken={step.enrolmentToken} onResult={flow.apply} />
      </AuthCard>
    );
  if (step.kind === "recoveryCodes") {
    const { codes, destination } = step;
    return (
      <AuthCard title={t("recovery.title")}>
        <RecoveryCodesStep codes={codes} onDone={() => flow.leave(destination)} />
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title={t("invite.title", { business: preview.tenant_name })}
      description={t("invite.body", {
        inviter: preview.invited_by || t("invite.someone"),
        role: preview.role.name,
        email: preview.email,
      })}
    >
      <form onSubmit={accept} className="space-y-4" noValidate>
        {!preview.existing_account ? (
          <FormField label={t("fullName")} error={fieldErrors.full_name} required>
            <Input
              autoComplete="name"
              className="h-11"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </FormField>
        ) : (
          <p className="text-muted-foreground text-sm">{t("invite.existingAccount")}</p>
        )}
        <FormField
          label={preview.existing_account ? t("password") : t("newPassword")}
          error={fieldErrors.password}
          required
        >
          <Input
            type="password"
            autoComplete={preview.existing_account ? "current-password" : "new-password"}
            className="h-11"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </FormField>
        {!preview.existing_account ? <PasswordStrength password={password} /> : null}
        {error && Object.keys(fieldErrors).length === 0 ? (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        ) : null}
        <Button type="submit" className="min-h-11 w-full" disabled={busy || !password}>
          <UserPlus aria-hidden />
          {t("invite.accept")}
        </Button>
      </form>
    </AuthCard>
  );
}
