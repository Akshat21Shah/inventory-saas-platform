"use client";

import { ImagePlus, Loader2, Trash2, TriangleAlert, X } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { FieldsDialog } from "@/components/shared/fields-dialog";
import { DateText } from "@/components/shared/money-text";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  catalogProductBarcodesCreate,
  catalogProductBarcodesDelete,
  catalogProductImagesDelete,
  catalogProductImagesUpload,
  catalogProductTaxRatesCancel,
  catalogProductTaxRatesSchedule,
  useCatalogProductImagesList,
} from "@/lib/api/generated/endpoints/catalog/catalog";
import type { ProductDetail } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { useTranslations } from "@/lib/i18n/translations";

import { percent, useTaxOptions } from "./options";

const STATE_VARIANT: Record<string, "default" | "secondary" | "outline"> = {
  CURRENT: "default",
  SCHEDULED: "secondary",
  PAST: "outline",
  CANCELLED: "outline",
};

export function TaxRatesPanel({
  product,
  onChanged,
}: {
  product: ProductDetail;
  onChanged: () => void;
}) {
  const t = useTranslations("catalog.taxRates");
  const errors = useErrorText();
  const { can } = useAuth();
  const tax = useTaxOptions();
  const manage = can("products.manage");
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-base">{t("title")}</CardTitle>
        {manage ? (
          <FieldsDialog
            trigger={
              <Button size="sm" variant="outline" className="min-h-9">
                {t("schedule")}
              </Button>
            }
            title={t("scheduleTitle")}
            description={t("scheduleBody")}
            fields={[
              {
                name: "gst_rate",
                label: t("rate"),
                kind: "select",
                required: true,
                options: tax.gstRates,
              },
              { name: "effective_from", label: t("from"), kind: "date", required: true },
              { name: "reason", label: t("reason") },
            ]}
            initial={{ gst_rate: "", effective_from: "", reason: "" }}
            submitLabel={t("schedule")}
            onSubmit={async (values) => {
              await catalogProductTaxRatesSchedule(product.id, {
                gst_rate: String(values.gst_rate),
                effective_from: String(values.effective_from),
                reason: String(values.reason),
              });
              toast.success(t("scheduled"));
              onChanged();
            }}
          />
        ) : null}
      </CardHeader>
      <CardContent>
        {product.current_rate ? null : (
          <p className="bg-warning/15 mb-3 flex gap-2 rounded-lg p-3 text-sm">
            <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
            {t("noCurrent")}
          </p>
        )}
        <ul className="divide-y">
          {product.tax_rates.map((rate) => (
            <li key={rate.id} className="flex items-center justify-between gap-2 py-2 text-sm">
              <span className="min-w-0">
                <span className="font-medium">{percent(rate.gst_rate)}</span>
                {rate.cess_type ? (
                  <span className="text-muted-foreground">
                    {" "}
                    + {rate.cess_type.name} {percent(rate.cess_rate)}
                  </span>
                ) : null}
                <span className="text-muted-foreground block text-xs">
                  {t("fromDate")} <DateText value={rate.effective_from} />
                  {rate.reason ? ` · ${rate.reason}` : ""}
                </span>
              </span>
              <span className="flex items-center gap-1">
                <Badge variant={STATE_VARIANT[rate.state] ?? "outline"}>
                  {t(`state.${rate.state}`)}
                </Badge>
                {manage && rate.state === "SCHEDULED" ? (
                  <ReasonDialog
                    destructive
                    trigger={
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-9"
                        aria-label={t("cancel")}
                        title={t("cancel")}
                      >
                        <X aria-hidden />
                      </Button>
                    }
                    title={t("cancelTitle")}
                    reasonLabel={t("reason")}
                    confirmLabel={t("cancel")}
                    onConfirm={async (reason) => {
                      try {
                        await catalogProductTaxRatesCancel(product.id, rate.id, { reason });
                        toast.success(t("cancelled"));
                        onChanged();
                      } catch (err) {
                        toast.error(errors.message(err));
                      }
                    }}
                  />
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

const IMAGE_TYPES = "image/jpeg,image/png,image/webp";

export function ImagesPanel({ productId }: { productId: string }) {
  const t = useTranslations("catalog.images");
  const errors = useErrorText();
  const { can } = useAuth();
  const manage = can("products.manage");
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const query = useCatalogProductImagesList(productId, {
    query: {
      // Resizing happens in the background: check again until every image is ready.
      refetchInterval: (q) =>
        (q.state.data?.data ?? []).some((image) => image.status === "PROCESSING") ? 2000 : false,
    },
  });
  const images = query.data?.data ?? [];

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        await catalogProductImagesUpload(productId, { file });
      }
      toast.success(t("uploaded"));
    } catch (err) {
      toast.error(errors.message(err));
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
      void query.refetch();
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-base">{t("title")}</CardTitle>
        {manage ? (
          <>
            <input
              ref={input}
              type="file"
              accept={IMAGE_TYPES}
              multiple
              className="sr-only"
              aria-label={t("choose")}
              onChange={(e) => void upload(e.target.files)}
            />
            <Button
              size="sm"
              variant="outline"
              className="min-h-9"
              disabled={uploading}
              onClick={() => input.current?.click()}
            >
              {uploading ? (
                <Loader2 aria-hidden className="animate-spin" />
              ) : (
                <ImagePlus aria-hidden />
              )}
              {t("add")}
            </Button>
          </>
        ) : null}
      </CardHeader>
      <CardContent>
        {images.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("none")}</p>
        ) : (
          <ul className="grid grid-cols-3 gap-2">
            {images.map((image) => (
              <li
                key={image.id}
                className="relative aspect-square overflow-hidden rounded-lg border"
              >
                {image.urls ? (
                  // eslint-disable-next-line @next/next/no-img-element -- long-cached public CDN image
                  <img
                    src={image.urls.thumb}
                    alt={image.alt_text}
                    className="size-full object-cover"
                  />
                ) : (
                  <span className="bg-muted text-muted-foreground flex size-full items-center justify-center p-1 text-center text-xs">
                    {image.status === "FAILED" ? t("failed") : t("processing")}
                  </span>
                )}
                {manage ? (
                  <ConfirmDialog
                    destructive
                    trigger={
                      <Button
                        variant="secondary"
                        size="icon"
                        className="absolute top-1 right-1 size-8"
                        aria-label={t("remove")}
                      >
                        <Trash2 aria-hidden />
                      </Button>
                    }
                    title={t("removeTitle")}
                    confirmLabel={t("remove")}
                    onConfirm={async () => {
                      await catalogProductImagesDelete(productId, image.id);
                      void query.refetch();
                    }}
                  />
                ) : null}
              </li>
            ))}
          </ul>
        )}
        <p className="text-muted-foreground mt-3 text-xs">{t("hint")}</p>
      </CardContent>
    </Card>
  );
}

export function BarcodesPanel({
  product,
  onChanged,
}: {
  product: ProductDetail;
  onChanged: () => void;
}) {
  const t = useTranslations("catalog.barcodes");
  const errors = useErrorText();
  const { can } = useAuth();
  const manage = can("products.manage");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {product.barcodes.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("none")}</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {product.barcodes.map((barcode) => (
              <li key={barcode.id}>
                <Badge variant="secondary" className="gap-1 font-mono">
                  {barcode.barcode}
                  {manage ? (
                    <button
                      type="button"
                      aria-label={t("remove", { barcode: barcode.barcode })}
                      className="hover:text-destructive"
                      onClick={async () => {
                        try {
                          await catalogProductBarcodesDelete(product.id, barcode.id);
                          onChanged();
                        } catch (err) {
                          toast.error(errors.message(err));
                        }
                      }}
                    >
                      <X aria-hidden className="size-3" />
                    </button>
                  ) : null}
                </Badge>
              </li>
            ))}
          </ul>
        )}
        {manage ? (
          <form
            className="flex gap-2"
            onSubmit={async (e) => {
              e.preventDefault();
              setError(null);
              try {
                await catalogProductBarcodesCreate(product.id, { barcode: value.trim() });
                setValue("");
                onChanged();
              } catch (err) {
                setError(errors.fields(err).barcode ?? errors.message(err));
              }
            }}
          >
            <Input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              aria-label={t("new")}
              placeholder={t("new")}
              className="h-10"
            />
            <Button type="submit" variant="outline" className="min-h-10" disabled={!value.trim()}>
              {t("add")}
            </Button>
          </form>
        ) : null}
        {error ? (
          <p role="alert" className="text-destructive text-xs font-medium">
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
