"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { LogIn } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { FormField } from "@/components/shared/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { authStaffChooseTenant, authStaffLogin } from "@/lib/api/generated/endpoints/auth/auth";
import { useErrorText } from "@/lib/api/use-error-text";
import { useTranslations } from "@/lib/i18n/translations";

import { ChoiceList, EnrolStep, MfaStep, RecoveryCodesStep, useSignInFlow } from "./sign-in-flow";

const schema = z.object({
  email: z.string().trim().min(1, "required").email("email"),
  password: z.string().min(1, "required"),
});
type Values = z.infer<typeof schema>;

/** Email + password for staff and super admins; the server applies the host rules (ADR-020). */
export function StaffSignIn() {
  const t = useTranslations("auth");
  const errors = useErrorText();
  const params = useSearchParams();
  const flow = useSignInFlow({ next: params.get("next"), handoffNext: "/manage" });
  const [formError, setFormError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      await flow.apply((await authStaffLogin(values)).data);
    } catch (err) {
      setFormError(errors.message(err));
      form.resetField("password");
    }
  });

  const { step } = flow;
  if (step.kind === "mfa") return <MfaStep mfaToken={step.mfaToken} onResult={flow.apply} />;
  if (step.kind === "enrol")
    return <EnrolStep enrolmentToken={step.enrolmentToken} onResult={flow.apply} />;
  if (step.kind === "recoveryCodes")
    return <RecoveryCodesStep codes={step.codes} onDone={() => flow.leave(step.destination)} />;
  if (step.kind === "chooseTenant") {
    return (
      <div className="space-y-3">
        <p className="text-muted-foreground text-sm">{t("chooseTenant")}</p>
        <ChoiceList
          items={step.tenants}
          getKey={(tenant) => tenant.id}
          render={(tenant) => ({ title: tenant.name, subtitle: tenant.slug })}
          onChoose={async (tenant) =>
            flow.apply(
              (
                await authStaffChooseTenant({
                  choice_token: step.choiceToken,
                  tenant_id: tenant.id,
                })
              ).data,
            )
          }
        />
      </div>
    );
  }

  const fieldError = (name: keyof Values) => {
    const code = form.formState.errors[name]?.message;
    return code ? t(`validation.${code}`) : undefined;
  };
  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <FormField label={t("email")} error={fieldError("email")} required>
        <Input type="email" autoComplete="username" className="h-11" {...form.register("email")} />
      </FormField>
      <FormField label={t("password")} error={fieldError("password")} required>
        <Input
          type="password"
          autoComplete="current-password"
          className="h-11"
          {...form.register("password")}
        />
      </FormField>
      {formError ? (
        <p role="alert" className="text-destructive text-sm font-medium">
          {formError}
        </p>
      ) : null}
      <Button
        type="submit"
        className="min-h-11 w-full"
        disabled={form.formState.isSubmitting || step.kind === "leaving"}
      >
        <LogIn aria-hidden />
        {t("signIn")}
      </Button>
      <p className="text-center text-sm">
        <Link href="/forgot-password" className="text-primary underline-offset-4 hover:underline">
          {t("forgotPassword")}
        </Link>
      </p>
    </form>
  );
}
