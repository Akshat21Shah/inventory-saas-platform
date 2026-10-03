"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { FormField } from "@/components/shared/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { authPasswordForgot, authPasswordReset } from "@/lib/api/generated/endpoints/auth/auth";
import { useErrorText } from "@/lib/api/use-error-text";

import { AuthCard } from "./auth-card";
import { PasswordStrength } from "./password-strength";

const forgotSchema = z.object({ email: z.string().trim().email("email") });

export function ForgotPasswordScreen() {
  const t = useTranslations("auth");
  const errors = useErrorText();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<{ email: string }>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { email: "" },
  });

  const onSubmit = form.handleSubmit(async ({ email }) => {
    setError(null);
    try {
      await authPasswordForgot({ email });
      setSent(true); // the same answer whether or not the account exists
    } catch (err) {
      setError(errors.message(err));
    }
  });

  return (
    <AuthCard
      title={t("forgot.title")}
      description={sent ? undefined : t("forgot.body")}
      footer={
        <Link href="/login" className="text-primary hover:underline">
          {t("backToSignIn")}
        </Link>
      }
    >
      {sent ? (
        <p role="status" className="flex items-start gap-2">
          <MailCheck aria-hidden className="text-primary mt-0.5 size-5 shrink-0" />
          {t("forgot.sent")}
        </p>
      ) : (
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <FormField
            label={t("email")}
            error={form.formState.errors.email ? t("validation.email") : undefined}
            required
          >
            <Input type="email" autoComplete="email" className="h-11" {...form.register("email")} />
          </FormField>
          {error ? (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          ) : null}
          <Button type="submit" className="min-h-11 w-full" disabled={form.formState.isSubmitting}>
            {t("forgot.submit")}
          </Button>
        </form>
      )}
    </AuthCard>
  );
}

const resetSchema = z
  .object({ password: z.string().min(10, "tooShort"), confirm: z.string() })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "mismatch" });

export function ResetPasswordScreen({ uid, token }: { uid: string; token: string }) {
  const t = useTranslations("auth");
  const errors = useErrorText();
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<{ password: string; confirm: string }>({
    resolver: zodResolver(resetSchema),
    defaultValues: { password: "", confirm: "" },
  });
  const password = useWatch({ control: form.control, name: "password" });

  const onSubmit = form.handleSubmit(async ({ password: newPassword }) => {
    setError(null);
    try {
      await authPasswordReset({ uid, token, new_password: newPassword });
      setDone(true);
    } catch (err) {
      setError(errors.fields(err).new_password ?? errors.message(err));
    }
  });

  if (done) {
    return (
      <AuthCard title={t("reset.doneTitle")}>
        <p role="status">{t("reset.doneBody")}</p>
        <Button asChild className="min-h-11 w-full">
          <Link href="/login">{t("backToSignIn")}</Link>
        </Button>
      </AuthCard>
    );
  }
  const e = form.formState.errors;
  return (
    <AuthCard title={t("reset.title")}>
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormField
          label={t("newPassword")}
          error={e.password ? t(`validation.${e.password.message}`) : undefined}
          required
        >
          <Input
            type="password"
            autoComplete="new-password"
            className="h-11"
            {...form.register("password")}
          />
        </FormField>
        <PasswordStrength password={password} />
        <FormField
          label={t("confirmPassword")}
          error={e.confirm ? t(`validation.${e.confirm.message}`) : undefined}
          required
        >
          <Input
            type="password"
            autoComplete="new-password"
            className="h-11"
            {...form.register("confirm")}
          />
        </FormField>
        {error ? (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        ) : null}
        <Button type="submit" className="min-h-11 w-full" disabled={form.formState.isSubmitting}>
          {t("reset.submit")}
        </Button>
      </form>
    </AuthCard>
  );
}
