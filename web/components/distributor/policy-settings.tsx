"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { PageHeader } from "@/components/shared/page-header";
import { DocumentNumbering } from "@/components/billing/numbering";
import { RegistrySettingsForm } from "@/components/shared/registry-settings-form";
import { PageSkeleton } from "@/components/shared/skeletons";
import { Card, CardContent } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import {
  settingsFeatureToggle,
  settingsValueReset,
  settingsValuesUpdate,
  useSettingsFeatures,
  useSettingsRegistry,
} from "@/lib/api/generated/endpoints/settings/settings";
import { useErrorText } from "@/lib/api/use-error-text";
import { useAuth } from "@/components/auth/auth-provider";

import { POLICY_GROUPS } from "./settings-nav";

/** One policy group (Tax, Invoicing, …) generated from the settings registry (PLAN §9). */
export function PolicySettings({ group }: { group: string }) {
  const t = useTranslations("distributorSettings");
  const query = useSettingsRegistry();
  if (!(POLICY_GROUPS as readonly string[]).includes(group)) {
    return <EmptyState title={t("unknownGroup")} />;
  }
  const rows = query.data?.data.filter((row) => row.group === group) ?? [];
  return (
    <>
      <PageHeader title={t(`nav.policies.${group}`)} description={t(`policyBodies.${group}`)} />
      {group === "invoicing" ? <DocumentNumbering /> : null}
      {query.isLoading ? (
        <PageSkeleton />
      ) : query.error || !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title={t("noSettings")} description={t("noSettingsBody")} />
      ) : (
        <RegistrySettingsForm
          key={group}
          rows={query.data.data}
          groups={[group]}
          onSave={async (values) => (await settingsValuesUpdate({ values })).data}
          onReset={async (key) => (await settingsValueReset(key)).data}
        />
      )}
    </>
  );
}

/** Optional modules the super admin allows this business to switch (spec 5.2). */
export function FeatureSettings() {
  const t = useTranslations("distributorSettings.features");
  const errors = useErrorText();
  const { can, reloadMe } = useAuth();
  const canEdit = can("settings.manage");
  const query = useSettingsFeatures();
  const [pending, setPending] = useState<string | null>(null);
  const features = query.data?.data ?? [];

  return (
    <>
      <PageHeader title={t("title")} description={t("body")} />
      {query.isLoading ? (
        <PageSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <Card>
          <CardContent className="divide-y py-2">
            {features.map((feature) => (
              <div key={feature.code} className="flex items-center justify-between gap-4 py-3">
                <div>
                  <p className="font-medium">{feature.name}</p>
                  <p className="text-muted-foreground text-sm">{feature.description}</p>
                  {!feature.tenant_toggleable ? (
                    <p className="text-muted-foreground text-xs">{t("managedByPlatform")}</p>
                  ) : null}
                </div>
                <Switch
                  aria-label={feature.name}
                  checked={feature.enabled}
                  disabled={!canEdit || !feature.tenant_toggleable || pending !== null}
                  onCheckedChange={async (enabled) => {
                    setPending(feature.code);
                    try {
                      await settingsFeatureToggle(feature.code, { enabled });
                      await Promise.all([query.refetch(), reloadMe()]);
                      toast.success(enabled ? t("turnedOn") : t("turnedOff"));
                    } catch (err) {
                      toast.error(errors.message(err));
                    } finally {
                      setPending(null);
                    }
                  }}
                />
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </>
  );
}
