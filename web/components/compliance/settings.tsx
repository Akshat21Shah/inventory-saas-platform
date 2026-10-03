"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { RegistrySettingsForm } from "@/components/shared/registry-settings-form";
import { CardSkeleton, PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  getGstCredentialsQueryKey,
  gstCredentialsSave,
  gstCredentialsVerify,
  useGstCredentials,
} from "@/lib/api/generated/endpoints/compliance/compliance";
import {
  settingsValueReset,
  settingsValuesUpdate,
  useSettingsRegistry,
} from "@/lib/api/generated/endpoints/settings/settings";
import type { GstCredentials, GstEnvironmentEnum } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { ProviderMessage } from "@/components/shared/provider-message";
import { useTranslations } from "@/lib/i18n/translations";
import { useGstFailure } from "./provider-line";

/** The distributor's own login with the GST provider (ADR-049 items 1, 7): saved encrypted,
 * never shown back, checked by the server in the background. */
function CredentialsCard({ saved }: { saved: GstCredentials }) {
  const t = useTranslations("compliance.settings");
  const gst = useGstFailure();
  const client = useQueryClient();
  const { message, fields } = useErrorText();
  const [environment, setEnvironment] = useState<GstEnvironmentEnum>(saved.environment);
  const [values, setValues] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: getGstCredentialsQueryKey() });

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setErrors({});
    try {
      await action();
      toast.success(done);
      setValues({});
      await refresh();
    } catch (err) {
      const byField = fields(err);
      setErrors(byField);
      if (!Object.keys(byField).length) toast.error(message(err));
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void run(() => gstCredentialsSave({ environment, values }), t("saved"));
  }

  const label = (name: string) => (t.has(`fields.${name}`) ? t(`fields.${name}`) : name);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          {t("credentialsTitle")}
          <StatusBadge status={saved.status} labels="connectionStatus" />
        </CardTitle>
        <CardDescription>{t("credentialsBody")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-muted-foreground">{t("provider")}</dt>
              <dd className="font-medium">{saved.provider}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("gstin")}</dt>
              <dd className="font-mono">{saved.gstin}</dd>
            </div>
          </dl>
          <FormField label={t("environment")} error={errors.environment}>
            <FormSelect
              value={environment}
              onValueChange={(value) => setEnvironment(value as GstEnvironmentEnum)}
              options={(["SANDBOX", "PRODUCTION"] as const).map((value) => ({
                value,
                label: t(`environments.${value}`),
              }))}
            />
          </FormField>
          <div className="grid gap-4 sm:grid-cols-2">
            {saved.field_names.map((name) => (
              <FormField
                key={name}
                label={label(name)}
                required={saved.required_fields.includes(name)}
                hint={
                  saved.saved[name]
                    ? t("savedHint", { value: saved.saved[name] ?? "" })
                    : t("notSaved")
                }
                error={errors[name]}
              >
                <Input
                  className="h-10"
                  type={/secret|password/.test(name) ? "password" : "text"}
                  autoComplete="off"
                  value={values[name] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [name]: e.target.value }))}
                />
              </FormField>
            ))}
          </div>
          {saved.status === "FAILED" && saved.last_error ? (
            <p role="alert" className="bg-destructive/10 rounded-lg p-3 text-sm">
              <ProviderMessage {...gst("login", null, saved.last_error)} />
            </p>
          ) : null}
          {saved.status === "VERIFIED" && saved.verified_at ? (
            <p className="text-muted-foreground text-sm">
              {t("verifiedAt")} <DateText value={saved.verified_at} withTime />
            </p>
          ) : null}
          {saved.status === "CHECKING" ? (
            <p className="text-muted-foreground text-sm" aria-live="polite">
              {t("checking")}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={busy} className="min-h-10">
              {t("save")}
            </Button>
            {Object.values(saved.saved).some(Boolean) ? (
              <Button
                type="button"
                variant="outline"
                disabled={busy || saved.status === "CHECKING"}
                className="min-h-10"
                onClick={() => void run(() => gstCredentialsVerify(), t("checkStarted"))}
              >
                {t("check")}
              </Button>
            ) : null}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

/** Settings → E-invoices & e-way bills: the GST provider login and the compliance rules. Only
 * while one of the two modules is on (the super admin switches them on). */
export function ComplianceSettings() {
  const t = useTranslations("compliance.settings");
  const { feature } = useAuth();
  const on = feature("einvoice") || feature("ewaybill");
  const credentials = useGstCredentials({
    query: {
      enabled: on,
      refetchInterval: (query) => (query.state.data?.data.status === "CHECKING" ? 2000 : false),
    },
  });
  const registry = useSettingsRegistry({ query: { enabled: on } });
  if (!on) return <EmptyState title={t("off")} description={t("offBody")} />;
  const rows = registry.data?.data ?? [];
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="space-y-6">
        {credentials.isLoading ? (
          <CardSkeleton />
        ) : credentials.error || !credentials.data ? (
          <ErrorState error={credentials.error} onRetry={() => void credentials.refetch()} />
        ) : (
          <CredentialsCard
            key={`${credentials.data.data.environment}-${credentials.data.data.status}`}
            saved={credentials.data.data}
          />
        )}
        <section className="space-y-2" aria-labelledby="compliance-rules">
          <h2 id="compliance-rules" className="font-semibold">
            {t("rulesTitle")}
          </h2>
          <p className="text-muted-foreground text-sm">{t("rulesBody")}</p>
          {registry.isLoading ? (
            <PageSkeleton />
          ) : registry.error ? (
            <ErrorState error={registry.error} onRetry={() => void registry.refetch()} />
          ) : (
            <RegistrySettingsForm
              rows={rows}
              groups={["compliance"]}
              onSave={async (values) => (await settingsValuesUpdate({ values })).data}
              onReset={async (key) => (await settingsValueReset(key)).data}
            />
          )}
        </section>
      </div>
    </>
  );
}
