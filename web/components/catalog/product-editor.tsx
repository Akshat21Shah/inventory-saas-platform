"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { Controller, useForm, useWatch, type Control } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useAuth } from "@/components/auth/auth-provider";
import { ProductPlanningCard } from "@/components/planning/product-planning";
import { ProductSuppliersPanel } from "@/components/purchasing/product-suppliers";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { ErrorState } from "@/components/shared/error-state";
import { FormField } from "@/components/shared/form-field";
import { FormActions } from "@/components/shared/form-actions";
import { FormSelect } from "@/components/shared/form-select";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
import { ProductStockCard } from "@/components/stock/stock-detail";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  catalogProductsCreate,
  catalogProductsDelete,
  catalogProductsUpdate,
  useCatalogHsnHint,
  useCatalogProductsRetrieve,
} from "@/lib/api/generated/endpoints/catalog/catalog";
import type { ProductDetail, Warning } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatMoney, formatQty } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";

import { BarcodesPanel, ImagesPanel, TaxRatesPanel } from "./product-panels";
import {
  percent,
  useBrandOptions,
  useCategoryOptions,
  useTaxOptions,
  useUnitOptions,
  type Option,
} from "./options";

const NONE = "none";
const DECIMAL = /^\d+(\.\d+)?$/;
const optionalDecimal = z
  .string()
  .trim()
  .refine((v) => v === "" || DECIMAL.test(v.replaceAll(",", "")), "decimal");
const requiredDecimal = z
  .string()
  .trim()
  .min(1, "required")
  .refine((v) => DECIMAL.test(v.replaceAll(",", "")), "decimal");

const schema = z.object({
  code: z.string().trim().min(1, "required"),
  name: z.string().trim().min(1, "required"),
  description: z.string(),
  category: z.string(),
  brand: z.string(),
  unit: z.string().min(1, "required"),
  pack_unit: z.string(),
  pack_size: optionalDecimal,
  hsn_code: z.string().trim().min(1, "required"),
  mrp: optionalDecimal,
  cost_price: optionalDecimal,
  base_price: requiredDecimal,
  min_order_qty: requiredDecimal,
  order_multiple: requiredDecimal,
  reorder_level: optionalDecimal,
  tags: z.string(),
  show_in_shop: z.boolean(),
  is_active: z.boolean(),
  gst_rate: z.string(),
  cess_type: z.string(),
  cess_rate: optionalDecimal,
  barcodes: z.string(),
});
type Values = z.infer<typeof schema>;

function initialValues(product?: ProductDetail): Values {
  return {
    code: product?.code ?? "",
    name: product?.name ?? "",
    description: product?.description ?? "",
    category: product?.category?.id ?? NONE,
    brand: product?.brand?.id ?? NONE,
    unit: product?.unit.id ?? "",
    pack_unit: product?.pack_unit?.id ?? NONE,
    pack_size: product?.pack_size ?? "",
    hsn_code: product?.hsn_code ?? "",
    mrp: product?.mrp ?? "",
    cost_price: product?.cost_price ?? "",
    base_price: product?.base_price ?? "",
    min_order_qty: product?.min_order_qty ?? "1",
    order_multiple: product?.order_multiple ?? "1",
    reorder_level: product?.reorder_level ?? "0",
    tags: (product?.tags ?? []).join(", "),
    show_in_shop: product?.show_in_shop ?? true,
    is_active: product?.is_active ?? true,
    gst_rate: "",
    cess_type: NONE,
    cess_rate: "",
    barcodes: "",
  };
}

const clean = (value: string) => value.trim().replaceAll(",", "");
const orNull = (value: string) => (value === NONE || value === "" ? null : value);
const list = (value: string) =>
  value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);

function SelectField({
  control,
  name,
  label,
  options,
  error,
  required,
  none,
  hint,
}: {
  control: Control<Values>;
  name: keyof Values;
  label: string;
  options: Option[];
  error?: string;
  required?: boolean;
  none?: string;
  hint?: string;
}) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => (
        <FormField label={label} error={error} required={required} hint={hint}>
          <FormSelect
            value={String(field.value)}
            onValueChange={field.onChange}
            options={none ? [{ value: NONE, label: none }, ...options] : options}
          />
        </FormField>
      )}
    />
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">{children}</CardContent>
    </Card>
  );
}

const MONEY_DETAILS = new Set(["mrp", "price_with_gst"]);

/** Server warning details as message arguments: money as ₹, rates without trailing zeros. */
function detailArgs(details: Record<string, unknown>): Record<string, string | number> {
  return Object.fromEntries(
    Object.entries(details).map(([key, value]) => {
      if (typeof value === "number") return [key, value];
      const text = String(value);
      if (MONEY_DETAILS.has(key)) return [key, formatMoney(text)];
      if (key.endsWith("_rate")) return [key, formatQty(text)];
      return [key, text];
    }),
  );
}

export function WarningList({
  warnings,
  keys = {},
}: {
  warnings: readonly Warning[];
  /** Message key per warning code, where a screen words a warning its own way. */
  keys?: Record<string, string>;
}) {
  const t = useTranslations("catalog.warnings");
  if (warnings.length === 0) return null;
  return (
    <div role="status" className="bg-warning/15 space-y-1 rounded-lg p-3 text-sm">
      {warnings.map((w) => (
        <p key={w.code} className="flex gap-2">
          <TriangleAlert aria-hidden className="text-warning-strong mt-0.5 size-4 shrink-0" />
          <span>
            {t.has(keys[w.code] ?? w.code)
              ? t(keys[w.code] ?? w.code, detailArgs(w.details))
              : w.message}
          </span>
        </p>
      ))}
    </div>
  );
}

function ProductForm({ product }: { product?: ProductDetail }) {
  const t = useTranslations("catalog.product");
  const tv = useTranslations("catalog.validation");
  const errors = useErrorText();
  const router = useRouter();
  const { can } = useAuth();
  const manage = can("products.manage");
  const categories = useCategoryOptions();
  const brands = useBrandOptions();
  const units = useUnitOptions();
  const tax = useTaxOptions();
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<readonly Warning[]>(product?.warnings ?? []);
  const creating = !product;

  const form = useForm<Values>({
    resolver: zodResolver(
      creating
        ? schema.refine((v) => v.gst_rate !== "", { path: ["gst_rate"], message: "required" })
        : schema,
    ),
    defaultValues: initialValues(product),
  });
  const [hsnCode, cessType, packUnit] = useWatch({
    control: form.control,
    name: ["hsn_code", "cess_type", "pack_unit"],
  });
  const hsn = useDebounced(hsnCode.replace(/\s/g, ""), 400);
  const hint = useCatalogHsnHint({ hsn }, { query: { enabled: hsn.length >= 2 } }).data?.data.hint;

  const fieldError = (name: keyof Values) => {
    const code = form.formState.errors[name]?.message;
    return serverErrors[name] ?? (code ? tv(code) : undefined);
  };

  const onSubmit = form.handleSubmit(async (v) => {
    setServerErrors({});
    setFormError(null);
    const common = {
      code: v.code.trim(),
      name: v.name.trim(),
      description: v.description,
      category: orNull(v.category),
      brand: orNull(v.brand),
      unit: v.unit,
      pack_unit: orNull(v.pack_unit),
      pack_size: v.pack_size ? clean(v.pack_size) : null,
      hsn_code: v.hsn_code.replace(/\s/g, ""),
      mrp: v.mrp ? clean(v.mrp) : null,
      base_price: clean(v.base_price),
      min_order_qty: clean(v.min_order_qty),
      order_multiple: clean(v.order_multiple),
      reorder_level: v.reorder_level ? clean(v.reorder_level) : "0",
      tags: list(v.tags),
      show_in_shop: v.show_in_shop,
      is_active: v.is_active,
      // Only staff who manage pricing send the cost (ADR-039); others never see it.
      ...(can("costs.manage") ? { cost_price: v.cost_price ? clean(v.cost_price) : null } : {}),
    };
    try {
      if (creating) {
        const response = await catalogProductsCreate({
          ...common,
          gst_rate: v.gst_rate,
          cess_type: orNull(v.cess_type),
          cess_rate: v.cess_rate ? clean(v.cess_rate) : "0",
          barcodes: list(v.barcodes),
        });
        toast.success(t("created"));
        router.replace(`/manage/products/${response.data.id}`);
      } else {
        const response = await catalogProductsUpdate(product.id, common);
        setWarnings(response.data.warnings);
        form.reset(initialValues(response.data));
        toast.success(t("saved"));
      }
    } catch (err) {
      const fields = errors.fields(err);
      setServerErrors(fields);
      if (Object.keys(fields).length === 0) setFormError(errors.message(err));
    }
  });

  return (
    <form onSubmit={onSubmit} className="space-y-6" noValidate>
      <WarningList warnings={warnings} />
      <fieldset disabled={!manage} className="space-y-6">
        <Section title={t("basics")}>
          <FormField label={t("code")} error={fieldError("code")} required hint={t("codeHint")}>
            <Input className="h-10" {...form.register("code")} />
          </FormField>
          <FormField label={t("name")} error={fieldError("name")} required>
            <Input className="h-10" {...form.register("name")} />
          </FormField>
          <SelectField
            control={form.control}
            name="category"
            label={t("category")}
            options={categories}
            none={t("noCategory")}
            error={fieldError("category")}
          />
          <SelectField
            control={form.control}
            name="brand"
            label={t("brand")}
            options={brands}
            none={t("noBrand")}
            error={fieldError("brand")}
          />
          <FormField label={t("description")} className="sm:col-span-2">
            <Textarea rows={3} {...form.register("description")} />
          </FormField>
          <FormField label={t("tags")} hint={t("tagsHint")} className="sm:col-span-2">
            <Input className="h-10" {...form.register("tags")} />
          </FormField>
        </Section>

        <Section title={t("priceAndTax")}>
          <FormField
            label={t("basePrice")}
            error={fieldError("base_price")}
            required
            hint={t("basePriceHint")}
          >
            <Input inputMode="decimal" className="h-10" {...form.register("base_price")} />
          </FormField>
          <FormField label={t("mrp")} error={fieldError("mrp")} hint={t("mrpHint")}>
            <Input inputMode="decimal" className="h-10" {...form.register("mrp")} />
          </FormField>
          {can("costs.view") ? (
            <FormField label={t("costPrice")} error={fieldError("cost_price")} hint={t("costHint")}>
              <Input
                inputMode="decimal"
                className="h-10"
                readOnly={!can("costs.manage")}
                {...form.register("cost_price")}
              />
            </FormField>
          ) : null}
          <FormField
            label={t("hsn")}
            error={fieldError("hsn_code")}
            required
            hint={hint ? t("hsnHint", { rate: percent(hint.gst_rate) }) : t("hsnHelp")}
          >
            <Input inputMode="numeric" className="h-10" {...form.register("hsn_code")} />
          </FormField>
          {creating ? (
            <>
              <SelectField
                control={form.control}
                name="gst_rate"
                label={t("gstRate")}
                options={tax.gstRates}
                error={fieldError("gst_rate")}
                required
              />
              <SelectField
                control={form.control}
                name="cess_type"
                label={t("cess")}
                options={tax.cessTypes}
                none={t("noCess")}
                error={fieldError("cess_type")}
              />
              {cessType !== NONE ? (
                <FormField label={t("cessRate")} error={fieldError("cess_rate")}>
                  <Input inputMode="decimal" className="h-10" {...form.register("cess_rate")} />
                </FormField>
              ) : null}
            </>
          ) : (
            <p className="text-muted-foreground text-sm sm:col-span-2">{t("gstChangesBelow")}</p>
          )}
        </Section>

        <Section title={t("ordering")}>
          <SelectField
            control={form.control}
            name="unit"
            label={t("unit")}
            options={units}
            error={fieldError("unit")}
            required
          />
          <FormField label={t("minOrderQty")} error={fieldError("min_order_qty")} required>
            <Input inputMode="decimal" className="h-10" {...form.register("min_order_qty")} />
          </FormField>
          <FormField
            label={t("orderMultiple")}
            error={fieldError("order_multiple")}
            required
            hint={t("orderMultipleHint")}
          >
            <Input inputMode="decimal" className="h-10" {...form.register("order_multiple")} />
          </FormField>
          <FormField label={t("reorderLevel")} error={fieldError("reorder_level")}>
            <Input inputMode="decimal" className="h-10" {...form.register("reorder_level")} />
          </FormField>
          <SelectField
            control={form.control}
            name="pack_unit"
            label={t("packUnit")}
            options={units}
            none={t("noPack")}
            error={fieldError("pack_unit")}
            hint={t("packHint")}
          />
          {packUnit !== NONE ? (
            <FormField label={t("packSize")} error={fieldError("pack_size")} required>
              <Input inputMode="decimal" className="h-10" {...form.register("pack_size")} />
            </FormField>
          ) : null}
          {creating ? (
            <FormField
              label={t("barcodes")}
              hint={t("barcodesHint")}
              error={fieldError("barcodes")}
            >
              <Input className="h-10" {...form.register("barcodes")} />
            </FormField>
          ) : null}
        </Section>

        <Section title={t("visibility")}>
          <Controller
            control={form.control}
            name="is_active"
            render={({ field }) => (
              <label className="flex items-center justify-between gap-4 sm:col-span-2">
                <span>
                  <span className="block text-sm font-medium">{t("active")}</span>
                  <span className="text-muted-foreground block text-xs">{t("activeHint")}</span>
                </span>
                <Switch checked={field.value} onCheckedChange={field.onChange} />
              </label>
            )}
          />
          <Controller
            control={form.control}
            name="show_in_shop"
            render={({ field }) => (
              <label className="flex items-center justify-between gap-4 sm:col-span-2">
                <span>
                  <span className="block text-sm font-medium">{t("showInShop")}</span>
                  <span className="text-muted-foreground block text-xs">{t("showInShopHint")}</span>
                </span>
                <Switch checked={field.value} onCheckedChange={field.onChange} />
              </label>
            )}
          />
        </Section>
      </fieldset>
      {formError ? (
        <p role="alert" className="text-destructive text-sm font-medium">
          {formError}
        </p>
      ) : null}
      {manage ? (
        <FormActions>
          {creating ? (
            <Button asChild variant="outline" className="min-h-11">
              <Link href="/manage/products">{t("cancel")}</Link>
            </Button>
          ) : (
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              disabled={!form.formState.isDirty}
              onClick={() => form.reset()}
            >
              {t("cancel")}
            </Button>
          )}
          <Button type="submit" className="min-h-11" disabled={form.formState.isSubmitting}>
            {creating ? t("create") : t("save")}
          </Button>
        </FormActions>
      ) : null}
    </form>
  );
}

function BackLink() {
  const t = useTranslations("catalog.product");
  return (
    <Button asChild variant="ghost" className="mb-2 -ml-3 min-h-10">
      <Link href="/manage/products">
        <ArrowLeft aria-hidden />
        {t("back")}
      </Link>
    </Button>
  );
}

export function NewProductPage() {
  const t = useTranslations("catalog.product");
  return (
    <>
      <BackLink />
      <PageHeader title={t("newTitle")} />
      <ProductForm />
    </>
  );
}

export function EditProductPage({ productId }: { productId: string }) {
  const t = useTranslations("catalog.product");
  const errors = useErrorText();
  const router = useRouter();
  const { can, feature } = useAuth();
  const query = useCatalogProductsRetrieve(productId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  const product = query.data.data;
  return (
    <>
      <BackLink />
      <PageHeader
        title={product.name}
        description={product.code}
        actions={
          can("products.manage") ? (
            <ConfirmDialog
              destructive
              trigger={
                <Button variant="outline" className="min-h-10">
                  {t("delete")}
                </Button>
              }
              title={t("deleteTitle", { name: product.name })}
              description={t("deleteBody")}
              confirmLabel={t("delete")}
              onConfirm={async () => {
                try {
                  await catalogProductsDelete(product.id);
                  toast.success(t("deleted"));
                  router.replace("/manage/products");
                } catch (err) {
                  toast.error(errors.message(err));
                }
              }}
            />
          ) : null
        }
      />
      <div className="grid gap-6 xl:grid-cols-[1fr_22rem]">
        <ProductForm key={product.updated_at} product={product} />
        <div className="space-y-6">
          {can("stock.view") ? <ProductStockCard productId={product.id} /> : null}
          <ProductPlanningCard productId={product.id} unit={product.unit.code} />
          <TaxRatesPanel product={product} onChanged={() => void query.refetch()} />
          <ImagesPanel productId={product.id} />
          <BarcodesPanel product={product} onChanged={() => void query.refetch()} />
          {feature("purchasing") && can("purchasing.view") ? (
            <ProductSuppliersPanel productId={product.id} />
          ) : null}
        </div>
      </div>
    </>
  );
}
