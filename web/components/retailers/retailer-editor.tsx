"use client";

import { ReminderPauseCard, RetailerConsentCard } from "@/components/notifications/manage/cards";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, MessageSquare, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { Controller, useForm, type Control } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useAuth } from "@/components/auth/auth-provider";
import type { Option } from "@/components/catalog/options";
import { WarningList } from "@/components/catalog/product-editor";
import { CopyPricingDialog } from "@/components/pricing/copy-pricing";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { FieldsDialog, type FieldValue } from "@/components/shared/fields-dialog";
import { FormField } from "@/components/shared/form-field";
import { FormActions } from "@/components/shared/form-actions";
import { FormSelect } from "@/components/shared/form-select";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  retailerPricesCreate,
  retailerPricesDelete,
  retailerPricesUpdate,
  useRetailersPriceSheet,
} from "@/lib/api/generated/endpoints/pricing/pricing";
import {
  retailersAddressesCreate,
  retailersAddressesDelete,
  retailersAddressesUpdate,
  retailersBlock,
  retailersCreate,
  retailersCreditUpdate,
  retailersDelete,
  retailersResendWelcome,
  retailersUnblock,
  retailersUpdate,
  useRetailersRetrieve,
} from "@/lib/api/generated/endpoints/retailers/retailers";
import type {
  Address,
  AddressKindEnum,
  PriceSheetRow,
  RetailerDetail,
  RetailerWritePreferredLanguageEnum,
  Warning,
} from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatQty } from "@/lib/format";
import { formatIndianMobile } from "@/lib/utils";

import { LANGUAGES, usePriceListOptions, useSalespeopleOptions, useStateOptions } from "./options";

const NONE = "none";
const schema = z.object({
  shop_name: z.string().trim().min(1, "required"),
  mobile: z.string().trim().min(1, "required"),
  owner_name: z.string(),
  email: z
    .string()
    .trim()
    .refine((v) => v === "" || z.email().safeParse(v).success, "email"),
  gstin: z.string(),
  state_code: z.string(),
  salesperson: z.string(),
  price_list: z.string(),
  preferred_language: z.string(),
  tags: z.string(),
  notes: z.string(),
  line1: z.string(),
  line2: z.string(),
  city: z.string(),
  district: z.string(),
  pincode: z.string(),
  address_state: z.string(),
});
type Values = z.infer<typeof schema>;

function initialValues(r?: RetailerDetail): Values {
  return {
    shop_name: r?.shop_name ?? "",
    mobile: r ? formatIndianMobile(r.mobile) : "",
    owner_name: r?.owner_name ?? "",
    email: r?.email ?? "",
    gstin: r?.gstin ?? "",
    state_code: r?.state_code || NONE,
    salesperson: r?.salesperson?.id ?? NONE,
    price_list: r?.price_list?.id ?? NONE,
    preferred_language: r?.preferred_language || "en",
    tags: (r?.tags ?? []).join(", "),
    notes: r?.notes ?? "",
    line1: "",
    line2: "",
    city: "",
    district: "",
    pincode: "",
    address_state: NONE,
  };
}

const orNull = (v: string) => (v === NONE || v === "" ? null : v);
const list = (v: string) =>
  v
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

function Select({
  control,
  name,
  label,
  options,
  error,
  none,
  hint,
}: {
  control: Control<Values>;
  name: keyof Values;
  label: string;
  options: Option[];
  error?: string;
  none?: string;
  hint?: string;
}) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => (
        <FormField label={label} error={error} hint={hint}>
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

function RetailerForm({ retailer }: { retailer?: RetailerDetail }) {
  const t = useTranslations("retailers.form");
  const tv = useTranslations("catalog.validation");
  const ta = useTranslations("auth.validation");
  const errors = useErrorText();
  const router = useRouter();
  const { can } = useAuth();
  const manage = can("retailers.manage");
  const states = useStateOptions();
  const salespeople = useSalespeopleOptions();
  const priceLists = usePriceListOptions();
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const creating = !retailer;
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: initialValues(retailer),
  });
  const fieldError = (name: keyof Values, server: string = name) => {
    const code = form.formState.errors[name]?.message;
    if (serverErrors[server]) return serverErrors[server];
    if (!code) return undefined;
    return code === "email" ? ta("email") : tv(code);
  };

  const onSubmit = form.handleSubmit(async (v) => {
    setServerErrors({});
    setFormError(null);
    const common = {
      shop_name: v.shop_name.trim(),
      mobile: v.mobile.replace(/\s/g, ""),
      owner_name: v.owner_name.trim(),
      email: v.email.trim(),
      gstin: v.gstin.replace(/\s/g, "").toUpperCase(),
      state_code: v.state_code === NONE ? "" : v.state_code,
      salesperson: orNull(v.salesperson),
      notes: v.notes,
      tags: list(v.tags),
      preferred_language: v.preferred_language as RetailerWritePreferredLanguageEnum,
      ...(can("pricing.manage") ? { price_list: orNull(v.price_list) } : {}),
    };
    try {
      if (creating) {
        const response = await retailersCreate({
          ...common,
          billing_address: v.line1.trim()
            ? {
                line1: v.line1.trim(),
                line2: v.line2.trim(),
                city: v.city.trim(),
                district: v.district.trim(),
                pincode: v.pincode.trim(),
                state_code: v.address_state === NONE ? common.state_code : v.address_state,
              }
            : null,
        });
        toast.success(t("created"));
        router.replace(`/manage/retailers/${response.data.id}`);
      } else {
        const response = await retailersUpdate(retailer.id, common);
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
      <fieldset disabled={!manage} className="space-y-6">
        <Section title={t("shop")}>
          <FormField label={t("shopName")} error={fieldError("shop_name")} required>
            <Input className="h-10" {...form.register("shop_name")} />
          </FormField>
          <FormField label={t("ownerName")} error={fieldError("owner_name")}>
            <Input className="h-10" {...form.register("owner_name")} />
          </FormField>
          <FormField
            label={t("mobile")}
            error={fieldError("mobile")}
            required
            hint={creating ? t("mobileHintNew") : t("mobileHint")}
          >
            <Input type="tel" inputMode="tel" className="h-10" {...form.register("mobile")} />
          </FormField>
          <FormField label={t("email")} error={fieldError("email")}>
            <Input type="email" className="h-10" {...form.register("email")} />
          </FormField>
          <FormField label={t("gstin")} error={fieldError("gstin")} hint={t("gstinHint")}>
            <Input className="h-10 uppercase" {...form.register("gstin")} />
          </FormField>
          <Select
            control={form.control}
            name="state_code"
            label={t("state")}
            options={states}
            none={t("noState")}
            error={fieldError("state_code")}
            hint={t("stateHint")}
          />
          <Select
            control={form.control}
            name="preferred_language"
            label={t("language")}
            options={LANGUAGES}
            error={fieldError("preferred_language")}
          />
          <FormField label={t("tags")} hint={t("tagsHint")}>
            <Input className="h-10" {...form.register("tags")} />
          </FormField>
        </Section>
        <Section title={t("selling")}>
          <Select
            control={form.control}
            name="salesperson"
            label={t("salesperson")}
            options={salespeople}
            none={t("noSalesperson")}
            error={fieldError("salesperson")}
          />
          {can("pricing.view") ? (
            <Select
              control={form.control}
              name="price_list"
              label={t("priceList")}
              options={priceLists}
              none={t("standardPrices")}
              error={fieldError("price_list")}
              hint={can("pricing.manage") ? t("priceListHint") : t("priceListReadOnly")}
            />
          ) : null}
          <FormField label={t("notes")} className="sm:col-span-2" hint={t("notesHint")}>
            <Textarea rows={2} {...form.register("notes")} />
          </FormField>
        </Section>
        {creating ? (
          <Section title={t("billingAddress")}>
            <FormField label={t("line1")} error={fieldError("line1", "billing_address.line1")}>
              <Input className="h-10" {...form.register("line1")} />
            </FormField>
            <FormField label={t("line2")}>
              <Input className="h-10" {...form.register("line2")} />
            </FormField>
            <FormField label={t("city")} error={fieldError("city", "billing_address.city")}>
              <Input className="h-10" {...form.register("city")} />
            </FormField>
            <FormField label={t("district")}>
              <Input className="h-10" {...form.register("district")} />
            </FormField>
            <FormField
              label={t("pincode")}
              error={fieldError("pincode", "billing_address.pincode")}
            >
              <Input inputMode="numeric" className="h-10" {...form.register("pincode")} />
            </FormField>
            <Select
              control={form.control}
              name="address_state"
              label={t("addressState")}
              options={states}
              none={t("sameAsShop")}
              error={fieldError("address_state", "billing_address.state_code")}
            />
          </Section>
        ) : null}
      </fieldset>
      {formError ? (
        <p role="alert" className="text-destructive text-sm font-medium">
          {formError}
        </p>
      ) : null}
      {manage && creating ? (
        <p className="text-muted-foreground text-right text-sm">{t("welcomeNote")}</p>
      ) : null}
      {manage ? (
        <FormActions>
          {creating ? (
            <Button asChild variant="outline" className="min-h-11">
              <Link href="/manage/retailers">{t("cancel")}</Link>
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

function CreditCard({ retailer, onChanged }: { retailer: RetailerDetail; onChanged: () => void }) {
  const t = useTranslations("retailers.credit");
  const { can } = useAuth();
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-base">{t("title")}</CardTitle>
        {can("credit.manage") ? (
          <FieldsDialog
            trigger={
              <Button size="sm" variant="outline" className="min-h-9">
                <Pencil aria-hidden />
                {t("edit")}
              </Button>
            }
            title={t("editTitle")}
            description={t("editBody")}
            fields={[
              { name: "credit_limit", label: t("limit"), kind: "decimal", hint: t("limitHint") },
              { name: "payment_terms_days", label: t("terms"), kind: "int", required: true },
            ]}
            initial={{
              credit_limit: retailer.credit_limit ?? "",
              payment_terms_days: String(retailer.payment_terms_days),
            }}
            submitLabel={t("save")}
            onSubmit={async (v) => {
              await retailersCreditUpdate(retailer.id, {
                credit_limit: String(v.credit_limit).trim().replaceAll(",", "") || null,
                payment_terms_days: Number(v.payment_terms_days || 0),
              });
              toast.success(t("saved"));
              onChanged();
            }}
          />
        ) : null}
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p className="flex justify-between gap-2">
          <span className="text-muted-foreground">{t("limit")}</span>
          {retailer.credit_limit ? <MoneyText value={retailer.credit_limit} /> : t("noLimit")}
        </p>
        <p className="flex justify-between gap-2">
          <span className="text-muted-foreground">{t("terms")}</span>
          {t("days", { count: retailer.payment_terms_days })}
        </p>
      </CardContent>
    </Card>
  );
}

const ADDRESS_FIELDS = (t: ReturnType<typeof useTranslations>, states: Option[]) => [
  {
    name: "kind",
    label: t("kind"),
    kind: "select" as const,
    required: true,
    options: [
      { value: "BILLING", label: t("BILLING") },
      { value: "SHIPPING", label: t("SHIPPING") },
    ],
  },
  { name: "label", label: t("label"), hint: t("labelHint") },
  { name: "line1", label: t("line1"), required: true },
  { name: "line2", label: t("line2") },
  { name: "city", label: t("city"), required: true },
  { name: "district", label: t("district") },
  { name: "pincode", label: t("pincode"), required: true },
  {
    name: "state_code",
    label: t("state"),
    kind: "select" as const,
    required: true,
    options: states,
  },
  { name: "is_default", label: t("isDefault"), kind: "bool" as const },
];

function addressPayload(v: Record<string, FieldValue>) {
  return {
    kind: String(v.kind) as AddressKindEnum,
    label: String(v.label),
    line1: String(v.line1),
    line2: String(v.line2),
    city: String(v.city),
    district: String(v.district),
    pincode: String(v.pincode),
    state_code: String(v.state_code),
    is_default: Boolean(v.is_default),
  };
}

function AddressesCard({
  retailer,
  onChanged,
}: {
  retailer: RetailerDetail;
  onChanged: () => void;
}) {
  const t = useTranslations("retailers.addresses");
  const errors = useErrorText();
  const { can } = useAuth();
  const manage = can("retailers.manage");
  const states = useStateOptions();
  const fields = ADDRESS_FIELDS(t, states);
  const blank = {
    kind: "SHIPPING",
    label: "",
    line1: "",
    line2: "",
    city: "",
    district: "",
    pincode: "",
    state_code: retailer.state_code,
    is_default: false,
  };
  const valuesOf = (a: Address) => ({
    kind: a.kind,
    label: a.label,
    line1: a.line1,
    line2: a.line2,
    city: a.city,
    district: a.district,
    pincode: a.pincode,
    state_code: a.state_code,
    is_default: a.is_default,
  });
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-base">{t("title")}</CardTitle>
        {manage ? (
          <FieldsDialog
            trigger={
              <Button size="sm" variant="outline" className="min-h-9">
                <Plus aria-hidden />
                {t("add")}
              </Button>
            }
            title={t("add")}
            fields={fields}
            initial={blank}
            submitLabel={t("save")}
            onSubmit={async (v) => {
              await retailersAddressesCreate(retailer.id, addressPayload(v));
              onChanged();
            }}
          />
        ) : null}
      </CardHeader>
      <CardContent>
        {retailer.addresses.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("none")}</p>
        ) : (
          <ul className="divide-y text-sm">
            {retailer.addresses.map((a) => (
              <li key={a.id} className="flex items-start justify-between gap-2 py-2">
                <span>
                  <span className="flex flex-wrap items-center gap-1 font-medium">
                    {a.label || t(a.kind)}
                    {a.is_default ? <Badge variant="secondary">{t("default")}</Badge> : null}
                  </span>
                  <span className="text-muted-foreground block">
                    {[a.line1, a.line2, a.city, a.district, a.pincode].filter(Boolean).join(", ")}
                  </span>
                </span>
                {manage ? (
                  <span className="flex shrink-0">
                    <FieldsDialog
                      trigger={
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-9"
                          aria-label={t("edit")}
                        >
                          <Pencil aria-hidden />
                        </Button>
                      }
                      title={t("edit")}
                      fields={fields}
                      initial={valuesOf(a)}
                      submitLabel={t("save")}
                      onSubmit={async (v) => {
                        await retailersAddressesUpdate(retailer.id, a.id, addressPayload(v));
                        onChanged();
                      }}
                    />
                    <ConfirmDialog
                      destructive
                      trigger={
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-9"
                          aria-label={t("remove")}
                        >
                          <Trash2 aria-hidden />
                        </Button>
                      }
                      title={t("removeTitle")}
                      confirmLabel={t("remove")}
                      onConfirm={async () => {
                        try {
                          await retailersAddressesDelete(retailer.id, a.id);
                          onChanged();
                        } catch (err) {
                          toast.error(errors.message(err));
                        }
                      }}
                    />
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** The shop's special price for one product, edited in place (empty removes it). */
function SpecialPriceCell({
  retailerId,
  row,
  onSaved,
}: {
  retailerId: string;
  row: PriceSheetRow;
  onSaved: (warnings: readonly Warning[]) => void;
}) {
  const t = useTranslations("retailers.prices");
  const errors = useErrorText();
  const [value, setValue] = useState(row.special?.price ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const typed = value.trim().replaceAll(",", "");
  const changed = typed !== (row.special?.price ?? "");
  async function save() {
    setBusy(true);
    setError(null);
    try {
      if (!typed && row.special) {
        await retailerPricesDelete(row.special.id);
        onSaved([]);
      } else if (row.special) {
        onSaved((await retailerPricesUpdate(row.special.id, { price: typed })).data.warnings);
      } else {
        const created = await retailerPricesCreate({
          retailer: retailerId,
          product: row.product.id,
          price: typed,
        });
        onSaved(created.data.warnings);
      }
      toast.success(t("specialSaved"));
    } catch (err) {
      setError(errors.fields(err).price ?? errors.message(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      className="flex items-center justify-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (changed) void save();
      }}
    >
      <Input
        inputMode="decimal"
        value={value}
        placeholder="—"
        onChange={(e) => setValue(e.target.value)}
        aria-label={t("specialFor", { name: row.product.name })}
        aria-invalid={Boolean(error)}
        title={error ?? undefined}
        className="h-9 w-24 text-right tabular-nums"
      />
      {changed ? (
        <Button type="submit" size="sm" className="min-h-9" disabled={busy}>
          {t("save")}
        </Button>
      ) : null}
      {error ? (
        <span role="alert" className="text-destructive text-xs">
          {error}
        </span>
      ) : null}
    </form>
  );
}

/** What this shop pays for each product today, from the server's price resolution. */
function PriceSheet({ retailerId }: { retailerId: string }) {
  const t = useTranslations("retailers.prices");
  const { can } = useAuth();
  const cursor = useCursor();
  const [warnings, setWarnings] = useState<readonly Warning[]>([]);
  const query = useRetailersPriceSheet(retailerId, { cursor: cursor.cursor });
  const page = query.data?.data;
  const columns: DataTableColumn<PriceSheetRow>[] = [
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <span>
          <span className="block font-medium">{row.original.product.name}</span>
          <span className="text-muted-foreground block text-xs">{row.original.product.code}</span>
        </span>
      ),
    },
    {
      id: "qty",
      header: t("atQty"),
      cell: ({ row }) => formatQty(row.original.result.qty),
    },
    {
      id: "base",
      header: t("base"),
      cell: ({ row }) => <MoneyText value={row.original.result.base_price} />,
    },
    {
      id: "price",
      header: t("price"),
      cell: ({ row }) => (
        <span className="flex flex-col items-end">
          <MoneyText value={row.original.result.unit_price} />
          <span className="text-muted-foreground text-xs">
            {t(`source.${row.original.result.price_source}`)}
          </span>
        </span>
      ),
    },
    {
      id: "discount",
      header: t("discount"),
      cell: ({ row }) =>
        row.original.result.discounts.length ? (
          <span className="flex flex-col items-end">
            <span>
              <MoneyText value={row.original.result.discount_total} /> (
              {formatQty(row.original.result.discount_percent, 2)}%)
            </span>
            <span className="text-muted-foreground text-xs">
              {row.original.result.discounts.map((d) => d.rule_name).join(" + ")}
            </span>
          </span>
        ) : (
          "—"
        ),
    },
    {
      id: "net",
      header: t("net"),
      cell: ({ row }) => (
        <MoneyText value={row.original.result.net_unit_price} className="font-medium" />
      ),
    },
    ...(can("pricing.manage")
      ? [
          {
            id: "special",
            header: t("special"),
            cell: ({ row }) => (
              <SpecialPriceCell
                key={`${row.original.product.id}-${row.original.special?.price ?? ""}`}
                retailerId={retailerId}
                row={row.original}
                onSaved={(next) => {
                  setWarnings(next);
                  void query.refetch();
                }}
              />
            ),
          } satisfies DataTableColumn<PriceSheetRow>,
        ]
      : []),
  ];
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold">{t("title")}</h2>
        <p className="text-muted-foreground text-sm">{t("description")}</p>
      </div>
      <WarningList warnings={warnings} keys={{ FREE_GOODS: "FREE_GOODS_SPECIAL" }} />
      <DataTable
        columns={columns}
        cardLayout={{
          product: "title",
          price: "primary",
          net: "primary",
          special: "primary",
          discount: "secondary",
          qty: "secondary",
          base: "secondary",
        }}
        data={page?.results ?? []}
        getRowId={(row) => row.product.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["qty", "base", "price", "discount", "net", "special"]}
        pagination={cursor.pagination(page)}
        empty={{ title: t("emptyTitle"), description: t("emptyBody") }}
      />
    </section>
  );
}

function BackLink() {
  const t = useTranslations("retailers.form");
  return (
    <Button asChild variant="ghost" className="mb-2 -ml-3 min-h-10">
      <Link href="/manage/retailers">
        <ArrowLeft aria-hidden />
        {t("back")}
      </Link>
    </Button>
  );
}

export function NewRetailerPage() {
  const t = useTranslations("retailers.form");
  return (
    <>
      <BackLink />
      <PageHeader title={t("newTitle")} />
      <RetailerForm />
    </>
  );
}

export function RetailerDetailPage({ retailerId }: { retailerId: string }) {
  const t = useTranslations("retailers.detail");
  const errors = useErrorText();
  const router = useRouter();
  const { can } = useAuth();
  const manage = can("retailers.manage");
  const query = useRetailersRetrieve(retailerId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  const retailer = query.data.data;
  const refresh = () => void query.refetch();
  const onHold = retailer.status === "BLOCKED";
  return (
    <>
      <BackLink />
      <PageHeader
        title={retailer.shop_name}
        description={`${retailer.code} · ${formatIndianMobile(retailer.mobile)}`}
        actions={
          manage ? (
            <>
              <ConfirmDialog
                trigger={
                  <Button variant="outline" className="min-h-10">
                    <MessageSquare aria-hidden />
                    {t("resendWelcome")}
                  </Button>
                }
                title={t("resendTitle")}
                description={t("resendBody", { mobile: formatIndianMobile(retailer.mobile) })}
                confirmLabel={t("resendWelcome")}
                onConfirm={async () => {
                  await retailersResendWelcome(retailer.id);
                  toast.success(t("resent"));
                  refresh();
                }}
              />
              {onHold ? (
                <ConfirmDialog
                  trigger={
                    <Button variant="outline" className="min-h-10">
                      {t("removeHold")}
                    </Button>
                  }
                  title={t("removeHoldTitle", { name: retailer.shop_name })}
                  confirmLabel={t("removeHold")}
                  onConfirm={async () => {
                    await retailersUnblock(retailer.id);
                    refresh();
                  }}
                />
              ) : (
                <ReasonDialog
                  destructive
                  trigger={
                    <Button variant="outline" className="min-h-10">
                      {t("putOnHold")}
                    </Button>
                  }
                  title={t("putOnHoldTitle", { name: retailer.shop_name })}
                  description={t("putOnHoldBody")}
                  reasonLabel={t("reason")}
                  confirmLabel={t("putOnHold")}
                  onConfirm={async (reason) => {
                    try {
                      await retailersBlock(retailer.id, { reason });
                      refresh();
                    } catch (err) {
                      toast.error(errors.message(err));
                    }
                  }}
                />
              )}
              <ConfirmDialog
                destructive
                trigger={
                  <Button variant="outline" className="min-h-10">
                    <Trash2 aria-hidden />
                    {t("delete")}
                  </Button>
                }
                title={t("deleteTitle", { name: retailer.shop_name })}
                description={t("deleteBody")}
                confirmLabel={t("delete")}
                onConfirm={async () => {
                  try {
                    await retailersDelete(retailer.id);
                    toast.success(t("deleted"));
                    router.replace("/manage/retailers");
                  } catch (err) {
                    toast.error(errors.message(err));
                  }
                }}
              />
            </>
          ) : null
        }
      />
      <div className="mb-6 flex flex-wrap items-center gap-2 text-sm">
        <StatusBadge status={retailer.status} />
        {onHold && retailer.blocked_reason ? (
          <span className="text-muted-foreground">{retailer.blocked_reason}</span>
        ) : null}
        <span className="text-muted-foreground">
          {retailer.welcome_sent_at ? (
            <>
              {t("welcomeSent")} <DateText value={retailer.welcome_sent_at} withTime />
            </>
          ) : (
            t("welcomeNotSent")
          )}
        </span>
      </div>
      <div className="grid gap-6 xl:grid-cols-[1fr_22rem]">
        <RetailerForm key={retailer.updated_at} retailer={retailer} />
        <div className="space-y-6">
          {can("ledger.view") ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t("accountTitle")}</CardTitle>
              </CardHeader>
              <CardContent>
                <Button asChild variant="outline" className="min-h-10 w-full">
                  <Link href={`/manage/retailers/${retailer.id}/ledger`}>{t("accountLink")}</Link>
                </Button>
              </CardContent>
            </Card>
          ) : null}
          <CreditCard retailer={retailer} onChanged={refresh} />
          <ReminderPauseCard retailerId={retailer.id} />
          <RetailerConsentCard retailerId={retailer.id} />
          <AddressesCard retailer={retailer} onChanged={refresh} />
          {can("pricing.view") ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t("pricingTitle")}</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                <Button asChild variant="outline" className="min-h-10">
                  <Link href={`/manage/retailers/${retailer.id}/discounts`}>
                    {t("discountGrid")}
                  </Link>
                </Button>
                {can("pricing.manage") ? (
                  <>
                    <Button asChild variant="outline" className="min-h-10">
                      <Link href={`/manage/pricing/discounts/new?retailer=${retailer.id}`}>
                        {t("addDiscount")}
                      </Link>
                    </Button>
                    <CopyPricingDialog
                      retailerId={retailer.id}
                      shopName={retailer.shop_name}
                      onCopied={refresh}
                    />
                  </>
                ) : null}
                <Button asChild variant="ghost" className="min-h-10">
                  <Link href={`/manage/pricing/special-prices?retailer=${retailer.id}`}>
                    {t("specialPrices")}
                  </Link>
                </Button>
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
      {can("pricing.view") ? (
        <div className="mt-10">
          <PriceSheet retailerId={retailer.id} />
        </div>
      ) : null}
    </>
  );
}
