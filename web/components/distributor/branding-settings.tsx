"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ImageIcon, Trash2, Upload } from "lucide-react";
import { useTranslations } from "@/lib/i18n/translations";
import { useRef, useState, type CSSProperties, type FormEvent } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { useHostBranding } from "@/components/auth/tenant-branding";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { ErrorState } from "@/components/shared/error-state";
import { FormField } from "@/components/shared/form-field";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  getSettingsBrandingQueryKey,
  settingsBrandingAssetDelete,
  settingsBrandingAssetUpload,
  settingsBrandingUpdate,
  useSettingsBranding,
} from "@/lib/api/generated/endpoints/settings/settings";
import type { Branding } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { brandCssVariables, DEFAULT_BRAND_COLOR, isHexColor } from "@/lib/theme/palette";

const ASSETS = [
  { kind: "logo", field: "logo_url" },
  { kind: "favicon", field: "favicon_url" },
  { kind: "app_icon", field: "app_icon_url" },
] as const;

/** How the shop owner's app will look: sign-in card, a button and availability badges. */
function Preview({ name, color, logo }: { name: string; color: string; logo: string | null }) {
  const t = useTranslations("distributorSettings.branding");
  const style = brandCssVariables(isHexColor(color) ? color : DEFAULT_BRAND_COLOR) as CSSProperties;
  return (
    <div style={style} aria-label={t("preview")} role="img" className="bg-muted/40 rounded-xl p-4">
      <div
        aria-hidden
        className="bg-background mx-auto max-w-xs space-y-4 rounded-xl border p-5 shadow-sm"
      >
        <div className="flex items-center gap-3">
          {logo ? (
            // eslint-disable-next-line @next/next/no-img-element -- presigned storage URL
            <img src={logo} alt="" className="size-10 rounded object-contain" />
          ) : (
            <span className="bg-primary text-primary-foreground flex size-10 items-center justify-center rounded font-semibold">
              {(name || "?").slice(0, 1).toUpperCase()}
            </span>
          )}
          <span className="font-semibold">{name || "—"}</span>
        </div>
        <div className="border-input text-muted-foreground h-10 rounded-md border px-3 py-2 text-sm">
          98765 43210
        </div>
        <div className="bg-primary text-primary-foreground flex h-11 items-center justify-center rounded-md text-sm font-medium">
          {t("previewButton")}
        </div>
        <div className="flex gap-2">
          <StatusBadge status="IN_STOCK" />
          <StatusBadge status="LOW_STOCK" />
        </div>
        <p className="text-primary text-sm font-medium">{t("previewLink")}</p>
      </div>
    </div>
  );
}

function AssetRow({
  kind,
  url,
  onChanged,
}: {
  kind: string;
  url: string | null;
  onChanged: (branding: Branding) => void;
}) {
  const t = useTranslations("distributorSettings.branding");
  const errors = useErrorText();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const label = t(`assets.${kind}`);

  async function upload(file: File) {
    setBusy(true);
    try {
      onChanged((await settingsBrandingAssetUpload(kind, { file })).data);
      toast.success(t("uploaded", { asset: label }));
    } catch (err) {
      toast.error(errors.fields(err).file ?? errors.message(err));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 py-3">
      <div className="bg-muted flex size-12 shrink-0 items-center justify-center overflow-hidden rounded border">
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element -- presigned storage URL
          <img src={url} alt={label} className="size-full object-contain" />
        ) : (
          <ImageIcon aria-hidden className="text-muted-foreground size-5" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{label}</p>
        <p className="text-muted-foreground text-xs">{t(`assetHints.${kind}`)}</p>
      </div>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="sr-only"
        aria-label={`${t("upload")}: ${label}`}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void upload(file);
        }}
      />
      <Button
        variant="outline"
        className="min-h-10"
        disabled={busy}
        onClick={() => input.current?.click()}
      >
        <Upload aria-hidden />
        {url ? t("replace") : t("upload")}
      </Button>
      {url ? (
        <ConfirmDialog
          destructive
          trigger={
            <Button
              variant="ghost"
              size="icon"
              className="size-10"
              disabled={busy}
              aria-label={`${t("remove")}: ${label}`}
            >
              <Trash2 aria-hidden />
            </Button>
          }
          title={t("removeTitle", { asset: label })}
          confirmLabel={t("remove")}
          onConfirm={async () => onChanged((await settingsBrandingAssetDelete(kind)).data)}
        />
      ) : null}
    </div>
  );
}

function BrandingEditor({ branding }: { branding: Branding }) {
  const t = useTranslations("distributorSettings.branding");
  const errors = useErrorText();
  const { applyBranding } = useHostBranding();
  const queryClient = useQueryClient();
  const { can } = useAuth();
  const canEdit = can("branding.manage");
  const [name, setName] = useState(branding.display_name);
  const [color, setColor] = useState(branding.primary_color || DEFAULT_BRAND_COLOR);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const dirty = name !== branding.display_name || color !== branding.primary_color;

  // The root layout renders the brand on the server; apply it in this tab now, without a reload.
  const applied = (next: Branding) => {
    queryClient.setQueryData(getSettingsBrandingQueryKey(), { data: next, status: 200 });
    applyBranding(next);
  };

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFieldErrors({});
    try {
      applied(
        (await settingsBrandingUpdate({ display_name: name.trim(), primary_color: color })).data,
      );
      toast.success(t("saved"));
    } catch (err) {
      const fields = errors.fields(err);
      setFieldErrors(fields);
      if (Object.keys(fields).length === 0) toast.error(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_22rem]">
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>
              <h2 className="text-lg">{t("identity")}</h2>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={save} className="grid gap-4" noValidate>
              <FormField
                label={t("displayName")}
                hint={t("displayNameHint")}
                error={fieldErrors.display_name}
              >
                <Input
                  className="h-10"
                  readOnly={!canEdit}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </FormField>
              <FormField label={t("color")} hint={t("colorHint")} error={fieldErrors.primary_color}>
                <div className="flex items-center gap-3">
                  <input
                    type="color"
                    aria-label={t("color")}
                    disabled={!canEdit}
                    className="size-10 cursor-pointer rounded border max-md:size-11"
                    value={isHexColor(color) ? color : DEFAULT_BRAND_COLOR}
                    onChange={(e) => setColor(e.target.value)}
                  />
                  <Input
                    className="h-10 w-32 font-mono"
                    aria-label={t("colorHex")}
                    readOnly={!canEdit}
                    value={color}
                    onChange={(e) => setColor(e.target.value.trim())}
                  />
                </div>
              </FormField>
              {canEdit ? (
                <div className="flex gap-2">
                  <Button type="submit" disabled={busy || !dirty} className="min-h-10">
                    {t("save")}
                  </Button>
                  {dirty ? (
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        setName(branding.display_name);
                        setColor(branding.primary_color);
                      }}
                    >
                      {t("discard")}
                    </Button>
                  ) : null}
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">{t("readOnly")}</p>
              )}
            </form>
          </CardContent>
        </Card>
        {canEdit ? (
          <Card>
            <CardHeader>
              <CardTitle>
                <h2 className="text-lg">{t("images")}</h2>
              </CardTitle>
            </CardHeader>
            <CardContent className="divide-y">
              {ASSETS.map(({ kind, field }) => (
                <AssetRow key={kind} kind={kind} url={branding[field]} onChanged={applied} />
              ))}
              <p className="text-muted-foreground pt-3 text-xs">{t("imageRules")}</p>
            </CardContent>
          </Card>
        ) : null}
      </div>
      <div className="space-y-2 xl:sticky xl:top-20 xl:self-start">
        <h2 className="text-sm font-medium">{t("preview")}</h2>
        <Preview name={name} color={color} logo={branding.logo_url} />
        <p className="text-muted-foreground text-xs">{t("previewNote")}</p>
      </div>
    </div>
  );
}

export function BrandingSettings() {
  const t = useTranslations("distributorSettings.branding");
  const query = useSettingsBranding();
  return (
    <>
      <PageHeader title={t("title")} description={t("body")} />
      {query.isLoading ? (
        <PageSkeleton />
      ) : query.error || !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <BrandingEditor
          key={`${query.data.data.display_name}|${query.data.data.primary_color}`}
          branding={query.data.data}
        />
      )}
    </>
  );
}
