"use client";

import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { useBrandOptions, useCategoryOptions } from "@/components/catalog/options";
import { WarningList } from "@/components/catalog/product-editor";
import { usePriceListOptions } from "@/components/retailers/options";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  discountRulesCreate,
  discountRulesDelete,
  discountRulesUpdate,
  useDiscountRulesList,
  useDiscountRulesRetrieve,
} from "@/lib/api/generated/endpoints/pricing/pricing";
import { useRetailersRetrieve } from "@/lib/api/generated/endpoints/retailers/retailers";
import type {
  AudienceTypeEnum,
  DiscountRule,
  DiscountTypeEnum,
  ScopeTypeEnum,
  Warning,
} from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatMoney, formatQty } from "@/lib/format";

import { ProductPicker, RetailerPicker, type Picked } from "./pickers";

const ALL = "all";
const clean = (v: string) => v.trim().replaceAll(",", "");

/** "10% off", "₹1.50 off each" — display only; the server decides what applies. */
function useValueText() {
  const t = useTranslations("pricing.discounts");
  return (type: string, value: string) =>
    type === "PERCENT"
      ? t("percentOff", { value: formatQty(value) })
      : t("rupeesOff", { value: formatMoney(value) });
}

function scopeText(t: ReturnType<typeof useTranslations>, rule: DiscountRule): string {
  if (rule.scope_type === "PRODUCT") return rule.product?.name ?? "";
  if (rule.scope_type === "CATEGORY") return t("inCategory", { name: rule.category?.name ?? "" });
  if (rule.scope_type === "BRAND") return t("ofBrand", { name: rule.brand?.name ?? "" });
  return t("allProducts");
}

function audienceText(t: ReturnType<typeof useTranslations>, rule: DiscountRule): string {
  if (rule.audience_type === "RETAILER") return rule.retailer?.shop_name ?? "";
  if (rule.audience_type === "PRICE_LIST")
    return t("onList", { name: rule.price_list?.name ?? "" });
  return t("allShops");
}

export function DiscountRulesPage() {
  const t = useTranslations("pricing.discounts");
  const valueText = useValueText();
  const { can } = useAuth();
  const cursor = useCursor();
  const [active, setActive] = useState(ALL);
  const query = useDiscountRulesList({
    cursor: cursor.cursor,
    active: active === ALL ? undefined : active === "active",
  });
  const page = query.data?.data;
  const columns: DataTableColumn<DiscountRule>[] = [
    {
      id: "name",
      header: t("name"),
      cell: ({ row }) => (
        <Link
          href={`/manage/pricing/discounts/${row.original.id}`}
          className="font-medium hover:underline"
        >
          {row.original.name}
        </Link>
      ),
    },
    {
      id: "discount",
      header: t("discount"),
      cell: ({ row }) =>
        row.original.slabs.length ? (
          <ul className="text-sm">
            {row.original.slabs.map((s) => (
              <li key={s.min_qty}>
                {t("slabLine", {
                  qty: formatQty(s.min_qty),
                  value: valueText(row.original.discount_type, s.value),
                })}
              </li>
            ))}
          </ul>
        ) : (
          valueText(row.original.discount_type, row.original.value)
        ),
    },
    { id: "on", header: t("appliesTo"), cell: ({ row }) => scopeText(t, row.original) },
    { id: "for", header: t("forShops"), cell: ({ row }) => audienceText(t, row.original) },
    {
      id: "dates",
      header: t("dates"),
      cell: ({ row }) =>
        row.original.valid_from || row.original.valid_to ? (
          <span className="text-sm whitespace-nowrap">
            {row.original.valid_from ? <DateText value={row.original.valid_from} /> : "…"} –{" "}
            {row.original.valid_to ? <DateText value={row.original.valid_to} /> : "…"}
          </span>
        ) : (
          t("always")
        ),
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => <StatusBadge status={row.original.is_active ? "ACTIVE" : "INACTIVE"} />,
    },
  ];
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          can("pricing.manage") ? (
            <Button asChild className="min-h-10">
              <Link href="/manage/pricing/discounts/new">
                <Plus aria-hidden />
                {t("add")}
              </Link>
            </Button>
          ) : undefined
        }
      />
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        pagination={cursor.pagination(page)}
        empty={{ title: t("emptyTitle"), description: t("emptyBody") }}
        toolbar={
          <FilterSelect
            label={t("status")}
            value={active}
            onChange={(v) => {
              setActive(v);
              cursor.reset();
            }}
            options={[
              { value: ALL, label: t("anyStatus") },
              { value: "active", label: t("activeOnly") },
              { value: "inactive", label: t("inactiveOnly") },
            ]}
          />
        }
      />
    </>
  );
}

interface SlabRow {
  min_qty: string;
  value: string;
}

function RuleForm({ rule, forShop }: { rule?: DiscountRule; forShop?: Picked }) {
  const t = useTranslations("pricing.discounts");
  const tc = useTranslations("common");
  const errors = useErrorText();
  const router = useRouter();
  const { can } = useAuth();
  const manage = can("pricing.manage");
  const categories = useCategoryOptions();
  const brands = useBrandOptions();
  const priceLists = usePriceListOptions();

  const [name, setName] = useState(rule?.name ?? "");
  const [type, setType] = useState<DiscountTypeEnum>(rule?.discount_type ?? "PERCENT");
  const [value, setValue] = useState(rule && !rule.slabs.length ? rule.value : "");
  const [useSlabs, setUseSlabs] = useState(Boolean(rule?.slabs.length));
  const [slabs, setSlabs] = useState<SlabRow[]>(
    rule?.slabs.length ? rule.slabs.map((s) => ({ ...s })) : [{ min_qty: "", value: "" }],
  );
  const [scope, setScope] = useState<ScopeTypeEnum>(rule?.scope_type ?? "ALL");
  const [product, setProduct] = useState<Picked | null>(
    rule?.product
      ? { id: rule.product.id, label: `${rule.product.name} (${rule.product.code})` }
      : null,
  );
  const [category, setCategory] = useState(rule?.category?.id ?? "");
  const [brand, setBrand] = useState(rule?.brand?.id ?? "");
  const [audience, setAudience] = useState<AudienceTypeEnum>(
    rule?.audience_type ?? (forShop ? "RETAILER" : "ALL"),
  );
  const [priceList, setPriceList] = useState(rule?.price_list?.id ?? "");
  const [shop, setShop] = useState<Picked | null>(
    rule?.retailer
      ? { id: rule.retailer.id, label: `${rule.retailer.shop_name} (${rule.retailer.code})` }
      : (forShop ?? null),
  );
  const [validFrom, setValidFrom] = useState(rule?.valid_from ?? "");
  const [validTo, setValidTo] = useState(rule?.valid_to ?? "");
  const [isActive, setIsActive] = useState(rule?.is_active ?? true);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<readonly Warning[]>([]);
  const [busy, setBusy] = useState(false);
  // After a create that warned, stay here: later saves update the new rule.
  const [savedId, setSavedId] = useState(rule?.id);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFieldErrors({});
    setFormError(null);
    const body = {
      name: name.trim(),
      discount_type: type,
      value: useSlabs ? "0" : clean(value) || "0",
      slabs: useSlabs
        ? slabs
            .filter((s) => s.min_qty.trim() || s.value.trim())
            .map((s) => ({ min_qty: clean(s.min_qty), value: clean(s.value) }))
        : [],
      scope_type: scope,
      product: scope === "PRODUCT" ? (product?.id ?? null) : null,
      category: scope === "CATEGORY" ? category || null : null,
      brand: scope === "BRAND" ? brand || null : null,
      audience_type: audience,
      price_list: audience === "PRICE_LIST" ? priceList || null : null,
      retailer: audience === "RETAILER" ? (shop?.id ?? null) : null,
      valid_from: validFrom || null,
      valid_to: validTo || null,
      is_active: isActive,
    };
    try {
      const response = savedId
        ? await discountRulesUpdate(savedId, body)
        : await discountRulesCreate(body);
      const saved = response.data;
      toast.success(t("saved"));
      setSavedId(saved.id);
      if (saved.warnings.length) {
        setWarnings(saved.warnings); // saved anyway (ADR-036); stay so it can be read
      } else {
        router.push("/manage/pricing/discounts");
      }
    } catch (err) {
      const fields = errors.fields(err);
      setFieldErrors(fields);
      if (Object.keys(fields).length === 0) setFormError(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  const unit = type === "PERCENT" ? "%" : "₹";
  return (
    <form onSubmit={submit} className="max-w-3xl space-y-6" noValidate>
      <WarningList warnings={warnings} />
      <fieldset disabled={!manage} className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("theDiscount")}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <FormField label={t("name")} required error={fieldErrors.name} hint={t("nameHint")}>
              <Input className="h-10" value={name} onChange={(e) => setName(e.target.value)} />
            </FormField>
            <FormField label={t("type")} required error={fieldErrors.discount_type}>
              <FormSelect
                value={type}
                onValueChange={(v) => setType(v as DiscountTypeEnum)}
                options={[
                  { value: "PERCENT", label: t("typePercent") },
                  { value: "FLAT_PER_UNIT", label: t("typeFlat") },
                ]}
              />
            </FormField>
            <label className="flex items-center justify-between gap-4 sm:col-span-2">
              <span>
                <span className="block text-sm font-medium">{t("useSlabs")}</span>
                <span className="text-muted-foreground block text-xs">{t("useSlabsHint")}</span>
              </span>
              <Switch checked={useSlabs} onCheckedChange={setUseSlabs} />
            </label>
            {useSlabs ? (
              <fieldset className="space-y-2 sm:col-span-2">
                <legend className="mb-2 text-sm font-medium">{t("slabs")}</legend>
                {slabs.map((slab, index) => (
                  <div key={index} className="flex flex-wrap items-end gap-2">
                    <FormField
                      label={t("fromQty")}
                      error={fieldErrors[`slabs.${index}.min_qty`]}
                      className="w-36"
                    >
                      <Input
                        inputMode="decimal"
                        className="h-10"
                        value={slab.min_qty}
                        onChange={(e) =>
                          setSlabs((all) =>
                            all.map((s, i) =>
                              i === index ? { ...s, min_qty: e.target.value } : s,
                            ),
                          )
                        }
                      />
                    </FormField>
                    <FormField
                      label={t("slabValue", { unit })}
                      error={fieldErrors[`slabs.${index}.value`]}
                      className="w-36"
                    >
                      <Input
                        inputMode="decimal"
                        className="h-10"
                        value={slab.value}
                        onChange={(e) =>
                          setSlabs((all) =>
                            all.map((s, i) => (i === index ? { ...s, value: e.target.value } : s)),
                          )
                        }
                      />
                    </FormField>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-10"
                      aria-label={t("removeSlab")}
                      disabled={slabs.length === 1}
                      onClick={() => setSlabs((all) => all.filter((_, i) => i !== index))}
                    >
                      <Trash2 aria-hidden />
                    </Button>
                  </div>
                ))}
                {fieldErrors.slabs ? (
                  <p role="alert" className="text-destructive text-xs font-medium">
                    {fieldErrors.slabs}
                  </p>
                ) : null}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setSlabs((all) => [...all, { min_qty: "", value: "" }])}
                >
                  <Plus aria-hidden />
                  {t("addSlab")}
                </Button>
              </fieldset>
            ) : (
              <FormField label={t("valueLabel", { unit })} required error={fieldErrors.value}>
                <Input
                  inputMode="decimal"
                  className="h-10"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                />
              </FormField>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("whoAndWhat")}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <FormField label={t("appliesTo")} required error={fieldErrors.scope_type}>
              <FormSelect
                value={scope}
                onValueChange={(v) => setScope(v as ScopeTypeEnum)}
                options={[
                  { value: "ALL", label: t("allProducts") },
                  { value: "CATEGORY", label: t("scopeCategory") },
                  { value: "BRAND", label: t("scopeBrand") },
                  { value: "PRODUCT", label: t("scopeProduct") },
                ]}
              />
            </FormField>
            {scope === "PRODUCT" ? (
              <FormField label={t("scopeProduct")} required error={fieldErrors.product}>
                <ProductPicker value={product} onChange={setProduct} />
              </FormField>
            ) : scope === "CATEGORY" ? (
              <FormField
                label={t("scopeCategory")}
                required
                error={fieldErrors.category}
                hint={t("categoryHint")}
              >
                <FormSelect value={category} onValueChange={setCategory} options={categories} />
              </FormField>
            ) : scope === "BRAND" ? (
              <FormField label={t("scopeBrand")} required error={fieldErrors.brand}>
                <FormSelect value={brand} onValueChange={setBrand} options={brands} />
              </FormField>
            ) : (
              <div />
            )}
            <FormField label={t("forShops")} required error={fieldErrors.audience_type}>
              <FormSelect
                value={audience}
                onValueChange={(v) => setAudience(v as AudienceTypeEnum)}
                options={[
                  { value: "ALL", label: t("allShops") },
                  { value: "PRICE_LIST", label: t("audiencePriceList") },
                  { value: "RETAILER", label: t("audienceShop") },
                ]}
              />
            </FormField>
            {audience === "PRICE_LIST" ? (
              <FormField label={t("audiencePriceList")} required error={fieldErrors.price_list}>
                <FormSelect value={priceList} onValueChange={setPriceList} options={priceLists} />
              </FormField>
            ) : audience === "RETAILER" ? (
              <FormField label={t("audienceShop")} required error={fieldErrors.retailer}>
                <RetailerPicker value={shop} onChange={setShop} />
              </FormField>
            ) : (
              <div />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("when")}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <FormField label={t("validFrom")} error={fieldErrors.valid_from} hint={t("datesHint")}>
              <Input
                type="date"
                className="h-10"
                value={validFrom}
                onChange={(e) => setValidFrom(e.target.value)}
              />
            </FormField>
            <FormField label={t("validTo")} error={fieldErrors.valid_to}>
              <Input
                type="date"
                className="h-10"
                value={validTo}
                onChange={(e) => setValidTo(e.target.value)}
              />
            </FormField>
            <label className="flex items-center justify-between gap-4 sm:col-span-2">
              <span className="text-sm font-medium">{t("isActive")}</span>
              <Switch checked={isActive} onCheckedChange={setIsActive} />
            </label>
          </CardContent>
        </Card>
        <p className="text-muted-foreground text-sm">{t("bestRuleNote")}</p>
      </fieldset>
      {formError ? (
        <p role="alert" className="text-destructive text-sm font-medium">
          {formError}
        </p>
      ) : null}
      {manage ? (
        <div className="flex justify-end gap-2">
          <Button asChild variant="outline" className="min-h-11">
            <Link href="/manage/pricing/discounts">{tc("cancel")}</Link>
          </Button>
          <Button type="submit" className="min-h-11" disabled={busy}>
            {savedId ? t("save") : t("create")}
          </Button>
        </div>
      ) : null}
    </form>
  );
}

function BackLink() {
  const t = useTranslations("pricing.discounts");
  return (
    <Button asChild variant="ghost" className="mb-2 -ml-3 min-h-10">
      <Link href="/manage/pricing/discounts">
        <ArrowLeft aria-hidden />
        {t("back")}
      </Link>
    </Button>
  );
}

export function NewDiscountRulePage() {
  const t = useTranslations("pricing.discounts");
  const params = useSearchParams();
  const retailerId = params.get("retailer") ?? "";
  const shop = useRetailersRetrieve(retailerId, { query: { enabled: Boolean(retailerId) } });
  if (retailerId && shop.isLoading) return <PageSkeleton />;
  const found = shop.data?.data;
  const forShop = found ? { id: found.id, label: `${found.shop_name} (${found.code})` } : undefined;
  return (
    <>
      <BackLink />
      <PageHeader title={forShop ? t("newTitleFor", { shop: found!.shop_name }) : t("newTitle")} />
      <RuleForm forShop={forShop} />
    </>
  );
}

export function EditDiscountRulePage({ ruleId }: { ruleId: string }) {
  const t = useTranslations("pricing.discounts");
  const errors = useErrorText();
  const router = useRouter();
  const { can } = useAuth();
  const query = useDiscountRulesRetrieve(ruleId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  const rule = query.data.data;
  return (
    <>
      <BackLink />
      <PageHeader
        title={rule.name}
        actions={
          can("pricing.manage") ? (
            <ConfirmDialog
              destructive
              trigger={
                <Button variant="outline" className="min-h-10">
                  <Trash2 aria-hidden />
                  {t("delete")}
                </Button>
              }
              title={t("deleteTitle", { name: rule.name })}
              confirmLabel={t("delete")}
              onConfirm={async () => {
                try {
                  await discountRulesDelete(rule.id);
                  router.replace("/manage/pricing/discounts");
                } catch (err) {
                  toast.error(errors.message(err));
                }
              }}
            />
          ) : undefined
        }
      />
      <RuleForm key={rule.updated_at} rule={rule} />
    </>
  );
}
