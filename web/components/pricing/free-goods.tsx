"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { usePriceListOptions } from "@/components/retailers/options";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { FormActions } from "@/components/shared/form-actions";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { useOfferText } from "@/components/shop/free-goods";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  freeGoodsSchemesCreate,
  freeGoodsSchemesDelete,
  freeGoodsSchemesUpdate,
  getFreeGoodsSchemesListQueryKey,
  getFreeGoodsSchemesRetrieveQueryKey,
  useFreeGoodsSchemesList,
  useFreeGoodsSchemesRetrieve,
} from "@/lib/api/generated/endpoints/pricing/pricing";
import type { AudienceTypeEnum, FreeGoodsScheme } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatQty } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";

import { ProductPicker, RetailerPicker, type Picked } from "./pickers";

const ALL = "all";
const clean = (v: string) => v.trim().replaceAll(",", "");

/** The section only while the ``free_goods`` module is on (ADR-056 item 7). */
export function FreeGoodsGate({ children }: { children: ReactNode }) {
  const t = useTranslations("pricing.freeGoods");
  const { me, feature } = useAuth();
  if (me && !feature("free_goods")) {
    return <EmptyState title={t("offTitle")} description={t("offBody")} />;
  }
  return <>{children}</>;
}

function audienceText(t: ReturnType<typeof useTranslations>, scheme: FreeGoodsScheme): string {
  if (scheme.audience_type === "RETAILER") return scheme.retailer?.shop_name ?? "";
  if (scheme.audience_type === "PRICE_LIST") {
    return t("onList", { name: scheme.price_list?.name ?? "" });
  }
  return t("allShops");
}

function sameProduct(scheme: FreeGoodsScheme): boolean {
  return scheme.buy_product.id === scheme.free_product.id;
}

export function FreeGoodsPage() {
  const t = useTranslations("pricing.freeGoods");
  const offerText = useOfferText();
  const { can } = useAuth();
  const cursor = useCursor();
  const [active, setActive] = useState(ALL);
  const [search, setSearch] = useState("");
  const debounced = useDebounced(search.trim());
  const query = useFreeGoodsSchemesList({
    cursor: cursor.cursor,
    search: debounced || undefined,
    active: active === ALL ? undefined : active === "active",
  });
  const page = query.data?.data;
  const columns: DataTableColumn<FreeGoodsScheme>[] = [
    {
      id: "name",
      header: t("name"),
      cell: ({ row }) => (
        <Link
          href={`/manage/pricing/free-goods/${row.original.id}`}
          className="font-medium hover:underline"
        >
          {row.original.name}
        </Link>
      ),
    },
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <span>
          {row.original.buy_product.name}
          <span className="text-muted-foreground block text-xs">
            {row.original.buy_product.code}
          </span>
        </span>
      ),
    },
    {
      id: "offer",
      header: t("offer"),
      cell: ({ row }) => {
        const s = row.original;
        return (
          <span>
            {offerText({
              buy_qty: s.buy_qty,
              free_qty: s.free_qty,
              same_product: sameProduct(s),
              free_product_name: s.free_product.name,
            })}
            <span className="text-muted-foreground block text-xs">
              {s.repeat ? t("repeats") : t("onceALine")}
              {s.max_free_qty ? ` · ${t("atMost", { qty: formatQty(s.max_free_qty) })}` : ""}
            </span>
          </span>
        );
      },
    },
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
  const filtering = Boolean(debounced) || active !== ALL;
  return (
    <FreeGoodsGate>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          can("pricing.manage") ? (
            <Button asChild className="min-h-10">
              <Link href="/manage/pricing/free-goods/new">
                <Plus aria-hidden />
                {t("add")}
              </Link>
            </Button>
          ) : null
        }
      />
      <DataTable
        columns={columns}
        cardLayout={{
          name: "title",
          offer: "primary",
          product: "primary",
          for: "primary",
          status: "primary",
          dates: "secondary",
        }}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={
          filtering
            ? { title: t("noMatchTitle"), description: t("noMatchBody") }
            : { title: t("emptyTitle"), description: t("emptyBody") }
        }
        toolbar={
          <FilterBar
            active={active === ALL ? 0 : 1}
            onClear={() => {
              setActive(ALL);
              cursor.reset();
            }}
            search={
              <Input
                type="search"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  cursor.reset();
                }}
                placeholder={t("searchPlaceholder")}
                aria-label={t("search")}
                className="h-10 w-full sm:w-64"
              />
            }
            filters={
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
        }
      />
    </FreeGoodsGate>
  );
}

function picked(ref: { id: string; name: string; code: string } | undefined): Picked | null {
  return ref ? { id: ref.id, label: `${ref.name} (${ref.code})` } : null;
}

function SchemeForm({ scheme }: { scheme?: FreeGoodsScheme }) {
  const t = useTranslations("pricing.freeGoods");
  const tc = useTranslations("common");
  const errors = useErrorText();
  const router = useRouter();
  const client = useQueryClient();
  const { can } = useAuth();
  const manage = can("pricing.manage");
  const priceLists = usePriceListOptions();
  const [name, setName] = useState(scheme?.name ?? "");
  const [buyProduct, setBuyProduct] = useState<Picked | null>(picked(scheme?.buy_product));
  const [buyQty, setBuyQty] = useState(scheme ? formatQty(scheme.buy_qty) : "");
  const [same, setSame] = useState(scheme ? sameProduct(scheme) : true);
  const [freeProduct, setFreeProduct] = useState<Picked | null>(picked(scheme?.free_product));
  const [freeQty, setFreeQty] = useState(scheme ? formatQty(scheme.free_qty) : "1");
  const [repeat, setRepeat] = useState(scheme?.repeat ?? true);
  const [maxFree, setMaxFree] = useState(
    scheme?.max_free_qty ? formatQty(scheme.max_free_qty) : "",
  );
  const [audience, setAudience] = useState<AudienceTypeEnum>(scheme?.audience_type ?? "ALL");
  const [priceList, setPriceList] = useState(scheme?.price_list?.id ?? "");
  const [shop, setShop] = useState<Picked | null>(
    scheme?.retailer
      ? { id: scheme.retailer.id, label: `${scheme.retailer.shop_name} (${scheme.retailer.code})` }
      : null,
  );
  const [validFrom, setValidFrom] = useState(scheme?.valid_from ?? "");
  const [validTo, setValidTo] = useState(scheme?.valid_to ?? "");
  const [isActive, setIsActive] = useState(scheme?.is_active ?? true);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFieldErrors({});
    setFormError(null);
    const body = {
      name: name.trim(),
      buy_product: buyProduct?.id ?? "",
      buy_qty: clean(buyQty) || "0",
      free_product: (same ? buyProduct?.id : freeProduct?.id) ?? "",
      free_qty: clean(freeQty) || "0",
      repeat,
      max_free_qty: clean(maxFree) || null,
      audience_type: audience,
      price_list: audience === "PRICE_LIST" ? priceList || null : null,
      retailer: audience === "RETAILER" ? (shop?.id ?? null) : null,
      valid_from: validFrom || null,
      valid_to: validTo || null,
      is_active: isActive,
    };
    try {
      if (scheme) await freeGoodsSchemesUpdate(scheme.id, body);
      else await freeGoodsSchemesCreate(body);
      await client.invalidateQueries({ queryKey: getFreeGoodsSchemesListQueryKey() });
      if (scheme) {
        await client.invalidateQueries({
          queryKey: getFreeGoodsSchemesRetrieveQueryKey(scheme.id),
        });
      }
      toast.success(t("saved"));
      router.push("/manage/pricing/free-goods");
    } catch (err) {
      const fields = errors.fields(err);
      setFieldErrors(fields);
      if (Object.keys(fields).length === 0) setFormError(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="max-w-3xl space-y-6" noValidate>
      <fieldset disabled={!manage} className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("theOffer")}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <FormField
              label={t("name")}
              required
              error={fieldErrors.name}
              hint={t("nameHint")}
              className="sm:col-span-2"
            >
              <Input className="h-10" value={name} onChange={(e) => setName(e.target.value)} />
            </FormField>
            <FormField label={t("buyProduct")} required error={fieldErrors.buy_product}>
              <ProductPicker value={buyProduct} onChange={setBuyProduct} />
            </FormField>
            <FormField label={t("buyQty")} required error={fieldErrors.buy_qty}>
              <Input
                inputMode="decimal"
                className="h-10"
                value={buyQty}
                onChange={(e) => setBuyQty(e.target.value)}
              />
            </FormField>
            <label className="flex items-center justify-between gap-4 sm:col-span-2">
              <span className="text-sm font-medium">{t("sameProduct")}</span>
              <Switch checked={same} onCheckedChange={setSame} />
            </label>
            {same ? null : (
              <FormField label={t("freeProduct")} required error={fieldErrors.free_product}>
                <ProductPicker value={freeProduct} onChange={setFreeProduct} />
              </FormField>
            )}
            <FormField label={t("freeQty")} required error={fieldErrors.free_qty}>
              <Input
                inputMode="decimal"
                className="h-10"
                value={freeQty}
                onChange={(e) => setFreeQty(e.target.value)}
              />
            </FormField>
            <label className="flex items-center justify-between gap-4 sm:col-span-2">
              <span>
                <span className="block text-sm font-medium">{t("repeat")}</span>
                <span className="text-muted-foreground block text-xs">{t("repeatHint")}</span>
              </span>
              <Switch checked={repeat} onCheckedChange={setRepeat} />
            </label>
            <FormField
              label={t("maxFree")}
              error={fieldErrors.max_free_qty}
              hint={t("maxFreeHint")}
            >
              <Input
                inputMode="decimal"
                className="h-10"
                value={maxFree}
                onChange={(e) => setMaxFree(e.target.value)}
              />
            </FormField>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("whoAndWhen")}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
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
        <p className="text-muted-foreground text-sm">{t("howItWorks")}</p>
      </fieldset>
      {formError ? (
        <p role="alert" className="text-destructive text-sm font-medium">
          {formError}
        </p>
      ) : null}
      {manage ? (
        <FormActions>
          <Button asChild variant="outline" className="min-h-11">
            <Link href="/manage/pricing/free-goods">{tc("cancel")}</Link>
          </Button>
          <Button type="submit" className="min-h-11" disabled={busy}>
            {scheme ? t("save") : t("create")}
          </Button>
        </FormActions>
      ) : null}
    </form>
  );
}

function BackLink() {
  const t = useTranslations("pricing.freeGoods");
  return (
    <Button asChild variant="ghost" className="mb-2 -ml-3 min-h-10">
      <Link href="/manage/pricing/free-goods">
        <ArrowLeft aria-hidden />
        {t("back")}
      </Link>
    </Button>
  );
}

export function NewFreeGoodsPage() {
  const t = useTranslations("pricing.freeGoods");
  return (
    <FreeGoodsGate>
      <BackLink />
      <PageHeader title={t("newTitle")} />
      <SchemeForm />
    </FreeGoodsGate>
  );
}

function EditScheme({ schemeId }: { schemeId: string }) {
  const t = useTranslations("pricing.freeGoods");
  const errors = useErrorText();
  const router = useRouter();
  const client = useQueryClient();
  const { can } = useAuth();
  const query = useFreeGoodsSchemesRetrieve(schemeId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  const scheme = query.data.data;
  return (
    <>
      <BackLink />
      <PageHeader
        title={scheme.name}
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
              title={t("deleteTitle", { name: scheme.name })}
              description={t("deleteBody")}
              confirmLabel={t("delete")}
              onConfirm={async () => {
                try {
                  await freeGoodsSchemesDelete(scheme.id);
                  await client.invalidateQueries({ queryKey: getFreeGoodsSchemesListQueryKey() });
                  router.replace("/manage/pricing/free-goods");
                } catch (err) {
                  toast.error(errors.message(err));
                }
              }}
            />
          ) : undefined
        }
      />
      <SchemeForm key={scheme.updated_at} scheme={scheme} />
    </>
  );
}

export function EditFreeGoodsPage({ schemeId }: { schemeId: string }) {
  return (
    <FreeGoodsGate>
      <EditScheme schemeId={schemeId} />
    </FreeGoodsGate>
  );
}
