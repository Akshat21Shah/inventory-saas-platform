"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FileSignature, Landmark, Trash2, Upload } from "lucide-react";
import { useTranslations } from "@/lib/i18n/translations";
import { useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { ErrorState } from "@/components/shared/error-state";
import { FormField } from "@/components/shared/form-field";
import { FormActions } from "@/components/shared/form-actions";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
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
import { Textarea } from "@/components/ui/textarea";
import { usePublicStatesList } from "@/lib/api/generated/endpoints/public/public";
import {
  getSettingsBankDetailsQueryKey,
  getSettingsBusinessQueryKey,
  settingsBankDetailsUpdate,
  settingsBrandingAssetDelete,
  settingsBrandingAssetUpload,
  settingsBusinessUpdate,
  useSettingsBankDetails,
  useSettingsBusiness,
} from "@/lib/api/generated/endpoints/settings/settings";
import type { BankDetails, Business } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";

const BUSINESS_FIELDS = [
  "name",
  "legal_name",
  "gstin",
  "state_code",
  "address_line1",
  "address_line2",
  "city",
  "pincode",
  "email",
  "phone",
] as const;
const INVOICE_FIELDS = ["invoice_terms", "invoice_footer", "signatory_name"] as const;
type EditableKey = (typeof BUSINESS_FIELDS)[number] | (typeof INVOICE_FIELDS)[number];

function useSaveState<T extends Record<string, string>>(initial: T) {
  const [values, setValues] = useState(initial);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const set = (key: keyof T, value: string) => {
    setValues((v) => ({ ...v, [key]: value }));
    setFieldErrors((e) => {
      const next = { ...e };
      delete next[key as string];
      return next;
    });
  };
  return { values, setValues, fieldErrors, setFieldErrors, set };
}

function BusinessForm({ business, canEdit }: { business: Business; canEdit: boolean }) {
  const t = useTranslations("distributorSettings.business");
  const tf = useTranslations("platform.onboarding.fields");
  const errors = useErrorText();
  const queryClient = useQueryClient();
  const states = usePublicStatesList();
  const initial = Object.fromEntries(
    [...BUSINESS_FIELDS, ...INVOICE_FIELDS].map((k) => [k, business[k] ?? ""]),
  ) as Record<EditableKey, string>;
  const form = useSaveState(initial);
  const [busy, setBusy] = useState(false);
  const changed = (Object.keys(initial) as EditableKey[]).filter(
    (k) => form.values[k] !== initial[k],
  );

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const body = Object.fromEntries(changed.map((k) => [k, form.values[k].trim()]));
      const updated = (await settingsBusinessUpdate(body)).data;
      queryClient.setQueryData(getSettingsBusinessQueryKey(), { data: updated, status: 200 });
      toast.success(t("saved"));
    } catch (err) {
      const fields = errors.fields(err);
      form.setFieldErrors(fields);
      if (Object.keys(fields).length === 0) toast.error(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  // Task 5.13: after the first invoice the GST identity changes only through the platform team.
  const locked = business.gst_identity_locked;
  const identity = (key: string) => locked && ["legal_name", "gstin", "state_code"].includes(key);
  const input = (key: EditableKey, label: string, upper = false) => (
    <FormField key={key} label={label} error={form.fieldErrors[key]}>
      <Input
        className="h-10"
        readOnly={!canEdit || identity(key)}
        value={form.values[key]}
        onChange={(e) => form.set(key, upper ? e.target.value.toUpperCase() : e.target.value)}
      />
    </FormField>
  );

  return (
    <form onSubmit={save} className="space-y-6">
      {canEdit ? null : (
        <p className="bg-muted rounded-lg p-3 text-sm" role="note">
          {t("readOnly")}
        </p>
      )}
      <Card>
        <CardHeader>
          <CardTitle>
            <h2 className="text-lg">{t("details")}</h2>
          </CardTitle>
          <CardDescription>{t("detailsBody")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {locked ? (
            <p className="bg-muted rounded-lg p-3 text-sm sm:col-span-2" role="note">
              {t("gstLocked")}
            </p>
          ) : null}
          {input("name", tf("name"))}
          {input("legal_name", tf("legal_name"))}
          {input("gstin", tf("gstin"), true)}
          <FormField label={tf("state_code")} error={form.fieldErrors.state_code}>
            <Select
              disabled={!canEdit || locked}
              value={form.values.state_code}
              onValueChange={(v) => form.set("state_code", v)}
            >
              <SelectTrigger className="min-h-10 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(states.data?.data ?? []).map((s) => (
                  <SelectItem key={s.code} value={s.code}>
                    {s.code} · {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          {input("address_line1", tf("address_line1"))}
          {input("address_line2", tf("address_line2"))}
          {input("city", tf("city"))}
          {input("pincode", tf("pincode"))}
          {input("email", tf("email"))}
          {input("phone", tf("phone"))}
          <p className="text-muted-foreground text-sm sm:col-span-2">
            {t("pan", { pan: business.pan || "—" })} · {t("webAddress", { slug: business.slug })}
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>
            <h2 className="text-lg">{t("invoice")}</h2>
          </CardTitle>
          <CardDescription>{t("invoiceBody")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <FormField label={t("invoiceTerms")} error={form.fieldErrors.invoice_terms}>
            <Textarea
              rows={3}
              readOnly={!canEdit}
              value={form.values.invoice_terms}
              onChange={(e) => form.set("invoice_terms", e.target.value)}
            />
          </FormField>
          <FormField label={t("invoiceFooter")} error={form.fieldErrors.invoice_footer}>
            <Input
              className="h-10"
              readOnly={!canEdit}
              value={form.values.invoice_footer}
              onChange={(e) => form.set("invoice_footer", e.target.value)}
            />
          </FormField>
          {input("signatory_name", t("signatoryName"))}
          {canEdit ? <SignatoryImage has={business.has_signatory_image} /> : null}
        </CardContent>
      </Card>
      {canEdit ? (
        <FormActions>
          <Button
            type="button"
            variant="outline"
            className="min-h-10"
            disabled={busy || changed.length === 0}
            onClick={() => form.setValues(initial)}
          >
            {t("cancel")}
          </Button>
          <Button type="submit" disabled={busy || changed.length === 0} className="min-h-10">
            {t("save")}
          </Button>
        </FormActions>
      ) : null}
    </form>
  );
}

function SignatoryImage({ has }: { has: boolean }) {
  const t = useTranslations("distributorSettings.business");
  const errors = useErrorText();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ queryKey: getSettingsBusinessQueryKey() });

  async function upload(file: File) {
    setBusy(true);
    try {
      await settingsBrandingAssetUpload("signatory", { file });
      await refresh();
      toast.success(t("signatoryUploaded"));
    } catch (err) {
      toast.error(errors.fields(err).file ?? errors.message(err));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <FileSignature aria-hidden className="text-muted-foreground size-5" />
      <span className="text-sm">{has ? t("signatorySet") : t("signatoryNone")}</span>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="sr-only"
        aria-label={t("uploadSignatory")}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void upload(file);
        }}
      />
      <Button
        type="button"
        variant="outline"
        className="min-h-10"
        disabled={busy}
        onClick={() => input.current?.click()}
      >
        <Upload aria-hidden />
        {t("uploadSignatory")}
      </Button>
      {has ? (
        <ConfirmDialog
          destructive
          trigger={
            <Button type="button" variant="ghost" className="min-h-10" disabled={busy}>
              <Trash2 aria-hidden />
              {t("remove")}
            </Button>
          }
          title={t("removeSignatory")}
          confirmLabel={t("remove")}
          onConfirm={async () => {
            await settingsBrandingAssetDelete("signatory");
            await refresh();
          }}
        />
      ) : null}
      <p className="text-muted-foreground w-full text-xs">{t("imageRules")}</p>
    </div>
  );
}

const BANK_FIELDS = [
  "bank_account_name",
  "bank_name",
  "bank_branch",
  "bank_ifsc",
  "upi_id",
] as const;

function BankForm({ bank }: { bank: BankDetails }) {
  const t = useTranslations("distributorSettings.bank");
  const errors = useErrorText();
  const queryClient = useQueryClient();
  const initial = {
    ...(Object.fromEntries(BANK_FIELDS.map((k) => [k, bank[k] ?? ""])) as Record<
      (typeof BANK_FIELDS)[number],
      string
    >),
    bank_account_number: "",
  };
  const form = useSaveState(initial);
  const [busy, setBusy] = useState(false);
  const changed = (Object.keys(initial) as (keyof typeof initial)[]).filter(
    (k) => form.values[k] !== initial[k],
  );

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const body = Object.fromEntries(changed.map((k) => [k, form.values[k].trim()]));
      const updated = (await settingsBankDetailsUpdate(body)).data;
      queryClient.setQueryData(getSettingsBankDetailsQueryKey(), { data: updated, status: 200 });
      form.setValues({
        ...(Object.fromEntries(BANK_FIELDS.map((k) => [k, updated[k] ?? ""])) as typeof initial),
        bank_account_number: "",
      });
      toast.success(t("saved"));
    } catch (err) {
      const fields = errors.fields(err);
      form.setFieldErrors(fields);
      if (Object.keys(fields).length === 0) toast.error(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2 className="flex items-center gap-2 text-lg">
            <Landmark aria-hidden className="size-5" />
            {t("title")}
          </h2>
        </CardTitle>
        <CardDescription>{t("body")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={save} className="grid gap-4 sm:grid-cols-2" noValidate>
          <FormField label={t("accountName")} error={form.fieldErrors.bank_account_name}>
            <Input
              className="h-10"
              value={form.values.bank_account_name}
              onChange={(e) => form.set("bank_account_name", e.target.value)}
            />
          </FormField>
          <FormField
            label={t("accountNumber")}
            hint={
              bank.bank_account_number_masked
                ? t("accountNumberHint", { masked: bank.bank_account_number_masked })
                : undefined
            }
            error={form.fieldErrors.bank_account_number}
          >
            <Input
              className="h-10"
              inputMode="numeric"
              autoComplete="off"
              value={form.values.bank_account_number}
              onChange={(e) => form.set("bank_account_number", e.target.value.replace(/\s/g, ""))}
            />
          </FormField>
          <FormField label={t("ifsc")} error={form.fieldErrors.bank_ifsc}>
            <Input
              className="h-10"
              value={form.values.bank_ifsc}
              onChange={(e) => form.set("bank_ifsc", e.target.value.toUpperCase())}
            />
          </FormField>
          <FormField label={t("bankName")} error={form.fieldErrors.bank_name}>
            <Input
              className="h-10"
              value={form.values.bank_name}
              onChange={(e) => form.set("bank_name", e.target.value)}
            />
          </FormField>
          <FormField label={t("branch")} error={form.fieldErrors.bank_branch}>
            <Input
              className="h-10"
              value={form.values.bank_branch}
              onChange={(e) => form.set("bank_branch", e.target.value)}
            />
          </FormField>
          <FormField label={t("upi")} error={form.fieldErrors.upi_id}>
            <Input
              className="h-10"
              value={form.values.upi_id}
              onChange={(e) => form.set("upi_id", e.target.value.trim())}
            />
          </FormField>
          <div className="sm:col-span-2">
            <Button type="submit" disabled={busy || changed.length === 0} className="min-h-10">
              {t("save")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export function BusinessSettings() {
  const t = useTranslations("distributorSettings.business");
  const { can, me } = useAuth();
  const canEdit = can("settings.manage");
  const business = useSettingsBusiness();
  // Bank details are for settings.manage only and never during a support session (ADR-029).
  const showBank = canEdit && !me?.impersonation;
  const bank = useSettingsBankDetails({ query: { enabled: showBank } });

  return (
    <>
      <PageHeader title={t("title")} description={t("body")} />
      {business.isLoading ? (
        <PageSkeleton />
      ) : business.error || !business.data ? (
        <ErrorState error={business.error} onRetry={() => void business.refetch()} />
      ) : (
        <div className="space-y-6">
          <BusinessForm
            key={JSON.stringify(business.data.data)}
            business={business.data.data}
            canEdit={canEdit}
          />
          {showBank ? (
            bank.error ? (
              <ErrorState error={bank.error} onRetry={() => void bank.refetch()} />
            ) : bank.data ? (
              <BankForm key={JSON.stringify(bank.data.data)} bank={bank.data.data} />
            ) : null
          ) : null}
        </div>
      )}
    </>
  );
}
