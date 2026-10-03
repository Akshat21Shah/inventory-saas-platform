"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Download, FileUp, History, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "@/lib/i18n/translations";
import { useState, type ReactNode } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { useStateOptions } from "@/components/retailers/options";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { FormActions } from "@/components/shared/form-actions";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { MoneyText, QtyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { getSuppliersExportUrl } from "@/lib/api/generated/endpoints/imports/imports";
import {
  suppliersCreate,
  suppliersDelete,
  suppliersUpdate,
  useSupplierProductsList,
  useSuppliersGet,
  useSuppliersList,
} from "@/lib/api/generated/endpoints/purchasing/purchasing";
import type { SupplierDetail, SupplierList, SupplierProduct } from "@/lib/api/generated/model";
import { downloadFile } from "@/lib/api/download";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { useListSearch } from "@/lib/list-search";
import { useDebounced } from "@/lib/use-debounced";

const ALL = "all";
const NONE = "none";

function BackLink() {
  const t = useTranslations("purchasing.suppliers");
  return (
    <Link
      href="/manage/purchasing/suppliers"
      className="text-muted-foreground hover:text-foreground mb-2 inline-flex min-h-11 items-center gap-1 text-sm"
    >
      <ArrowLeft aria-hidden className="size-4" />
      {t("back")}
    </Link>
  );
}

export function SuppliersPage() {
  const t = useTranslations("purchasing.suppliers");
  const { can } = useAuth();
  const errors = useErrorText();
  const manage = can("purchasing.manage");
  const [search, setSearch] = useListSearch();
  const [status, setStatus] = useState(ALL);
  const cursor = useCursor();
  const debounced = useDebounced(search.trim());
  const query = useSuppliersList({
    cursor: cursor.cursor,
    search: debounced || undefined,
    active: status === ALL ? undefined : status === "active",
  });
  const page = query.data?.data;
  const rows = page?.results ?? [];

  async function exportAs(fileType: "xlsx" | "csv") {
    try {
      await downloadFile(getSuppliersExportUrl({ file_type: fileType }), `suppliers.${fileType}`);
    } catch (err) {
      toast.error(errors.message(err));
    }
  }

  const columns: DataTableColumn<SupplierList>[] = [
    {
      id: "name",
      header: t("name"),
      cell: ({ row }) => (
        <Link
          href={`/manage/purchasing/suppliers/${row.original.id}`}
          className="block hover:underline"
        >
          <span className="block font-medium">{row.original.name}</span>
          <span className="text-muted-foreground block text-xs">
            {row.original.code}
            {row.original.gstin ? ` · ${row.original.gstin}` : ""}
          </span>
        </Link>
      ),
    },
    {
      id: "contact",
      header: t("contact"),
      cell: ({ row }) =>
        [row.original.contact_name, row.original.phone].filter(Boolean).join(" · ") || "—",
    },
    { id: "city", header: t("city"), cell: ({ row }) => row.original.city || "—" },
    {
      id: "delivery",
      header: t("delivery"),
      cell: ({ row }) =>
        row.original.lead_time_days
          ? t("days", { count: row.original.lead_time_days })
          : t("usualDays"),
    },
    {
      id: "products",
      header: t("products"),
      cell: ({ row }) => <span className="tabular-nums">{row.original.product_count}</span>,
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => <StatusBadge status={row.original.is_active ? "ACTIVE" : "INACTIVE"} />,
    },
  ];

  const filtering = Boolean(debounced) || status !== ALL;
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" className="min-h-10">
                  <Download aria-hidden />
                  {t("export")}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => void exportAs("xlsx")}>
                  {t("exportExcel")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => void exportAs("csv")}>
                  {t("exportCsv")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            {manage ? (
              <>
                <Button asChild variant="outline" className="min-h-10">
                  <Link href="/manage/purchasing/suppliers/from-receipts">
                    <History aria-hidden />
                    {t("fromReceipts")}
                  </Link>
                </Button>
                <Button asChild variant="outline" className="min-h-10">
                  <Link href="/manage/imports/new?kind=SUPPLIERS">
                    <FileUp aria-hidden />
                    {t("import")}
                  </Link>
                </Button>
                <Button asChild className="min-h-10">
                  <Link href="/manage/purchasing/suppliers/new">
                    <Plus aria-hidden />
                    {t("add")}
                  </Link>
                </Button>
              </>
            ) : null}
          </>
        }
      />
      <DataTable
        columns={columns}
        data={rows}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["products"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={
          filtering
            ? { title: t("noMatchTitle"), description: t("noMatchBody") }
            : {
                title: t("emptyTitle"),
                description: t("emptyBody"),
                action: manage ? (
                  <Button asChild className="min-h-11">
                    <Link href="/manage/purchasing/suppliers/new">{t("addFirst")}</Link>
                  </Button>
                ) : undefined,
              }
        }
        cardLayout={{
          name: "title",
          contact: "primary",
          delivery: "primary",
          status: "primary",
          city: "secondary",
          products: "secondary",
        }}
        toolbar={
          <FilterBar
            active={status !== ALL ? 1 : 0}
            onClear={() => {
              setStatus(ALL);
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
                value={status}
                onChange={(value) => {
                  setStatus(value);
                  cursor.reset();
                }}
                options={[
                  { value: ALL, label: t("anyStatus") },
                  { value: "active", label: t("active") },
                  { value: "inactive", label: t("inactive") },
                ]}
              />
            }
          />
        }
      />
    </>
  );
}

// --- One supplier ---------------------------------------------------------------------------

const DAYS = /^\d{0,3}$/;
const schema = z.object({
  name: z.string().trim().min(1, "required"),
  gstin: z.string(),
  state_code: z.string(),
  contact_name: z.string(),
  phone: z.string(),
  email: z
    .string()
    .trim()
    .refine((v) => v === "" || z.email().safeParse(v).success, "email"),
  address_line1: z.string(),
  address_line2: z.string(),
  city: z.string(),
  pincode: z.string(),
  payment_terms_days: z.string().regex(DAYS, "number"),
  lead_time_days: z.string().regex(DAYS, "number"),
  notes: z.string(),
  is_active: z.boolean(),
});
type Values = z.infer<typeof schema>;

function initialValues(s?: SupplierDetail): Values {
  return {
    name: s?.name ?? "",
    gstin: s?.gstin ?? "",
    state_code: s?.state_code ?? NONE,
    contact_name: s?.contact_name ?? "",
    phone: s?.phone ?? "",
    email: s?.email ?? "",
    address_line1: s?.address_line1 ?? "",
    address_line2: s?.address_line2 ?? "",
    city: s?.city ?? "",
    pincode: s?.pincode ?? "",
    payment_terms_days: String(s?.payment_terms_days ?? 0),
    lead_time_days: s?.lead_time_days ? String(s.lead_time_days) : "",
    notes: s?.notes ?? "",
    is_active: s?.is_active ?? true,
  };
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

function SupplierForm({ supplier }: { supplier?: SupplierDetail }) {
  const t = useTranslations("purchasing.supplierForm");
  const tv = useTranslations("catalog.validation");
  const ta = useTranslations("auth.validation");
  const errors = useErrorText();
  const router = useRouter();
  const { can } = useAuth();
  const manage = can("purchasing.manage");
  const states = useStateOptions();
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const creating = !supplier;
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: initialValues(supplier),
  });
  const fieldError = (name: keyof Values, server: string = name) => {
    if (serverErrors[server]) return serverErrors[server];
    const code = form.formState.errors[name]?.message;
    if (!code) return undefined;
    return code === "email" ? ta("email") : tv(code);
  };

  const onSubmit = form.handleSubmit(async (v) => {
    setServerErrors({});
    setFormError(null);
    const body = {
      name: v.name.trim(),
      gstin: v.gstin.replace(/\s/g, "").toUpperCase() || null,
      state_code: v.state_code === NONE ? null : v.state_code,
      contact_name: v.contact_name.trim(),
      phone: v.phone.trim(),
      email: v.email.trim(),
      address_line1: v.address_line1.trim(),
      address_line2: v.address_line2.trim(),
      city: v.city.trim(),
      pincode: v.pincode.trim(),
      payment_terms_days: Number(v.payment_terms_days || 0),
      lead_time_days: v.lead_time_days ? Number(v.lead_time_days) : null,
      notes: v.notes,
      is_active: v.is_active,
    };
    try {
      if (creating) {
        const response = await suppliersCreate(body);
        toast.success(t("created"));
        router.replace(`/manage/purchasing/suppliers/${response.data.id}`);
      } else {
        const response = await suppliersUpdate(supplier.id, body);
        form.reset(initialValues(response.data));
        toast.success(t("saved"));
      }
    } catch (err) {
      const fields = errors.fields(err);
      if (fields.state_id) fields.state_code = fields.state_id;
      setServerErrors(fields);
      if (Object.keys(fields).length === 0) setFormError(errors.message(err));
    }
  });

  return (
    <form onSubmit={onSubmit} className="space-y-6" noValidate>
      <fieldset disabled={!manage} className="space-y-6">
        <Section title={t("supplier")}>
          <FormField label={t("name")} error={fieldError("name")} required>
            <Input className="h-10" {...form.register("name")} />
          </FormField>
          <FormField label={t("gstin")} error={fieldError("gstin")} hint={t("gstinHint")}>
            <Input className="h-10 uppercase" {...form.register("gstin")} />
          </FormField>
          <Controller
            control={form.control}
            name="state_code"
            render={({ field }) => (
              <FormField label={t("state")} error={fieldError("state_code")} hint={t("stateHint")}>
                <FormSelect
                  value={field.value}
                  onValueChange={field.onChange}
                  options={[{ value: NONE, label: t("noState") }, ...states]}
                />
              </FormField>
            )}
          />
          <FormField label={t("contactName")} error={fieldError("contact_name")}>
            <Input className="h-10" {...form.register("contact_name")} />
          </FormField>
          <FormField label={t("phone")} error={fieldError("phone")}>
            <Input type="tel" inputMode="tel" className="h-10" {...form.register("phone")} />
          </FormField>
          <FormField label={t("email")} error={fieldError("email")} hint={t("emailHint")}>
            <Input type="email" className="h-10" {...form.register("email")} />
          </FormField>
        </Section>
        <Section title={t("buying")}>
          <FormField
            label={t("leadTime")}
            error={fieldError("lead_time_days")}
            hint={t("leadTimeHint")}
          >
            <Input inputMode="numeric" className="h-10" {...form.register("lead_time_days")} />
          </FormField>
          <FormField label={t("terms")} error={fieldError("payment_terms_days")}>
            <Input inputMode="numeric" className="h-10" {...form.register("payment_terms_days")} />
          </FormField>
          <Controller
            control={form.control}
            name="is_active"
            render={({ field }) => (
              <FormField label={t("active")} hint={t("activeHint")}>
                <Switch
                  checked={field.value}
                  onCheckedChange={field.onChange}
                  aria-label={t("active")}
                />
              </FormField>
            )}
          />
          <FormField label={t("notes")} className="sm:col-span-2">
            <Textarea rows={2} {...form.register("notes")} />
          </FormField>
        </Section>
        <Section title={t("address")}>
          <FormField label={t("line1")} error={fieldError("address_line1")}>
            <Input className="h-10" {...form.register("address_line1")} />
          </FormField>
          <FormField label={t("line2")} error={fieldError("address_line2")}>
            <Input className="h-10" {...form.register("address_line2")} />
          </FormField>
          <FormField label={t("city")} error={fieldError("city")}>
            <Input className="h-10" {...form.register("city")} />
          </FormField>
          <FormField label={t("pincode")} error={fieldError("pincode")}>
            <Input inputMode="numeric" className="h-10" {...form.register("pincode")} />
          </FormField>
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
              <Link href="/manage/purchasing/suppliers">{t("cancel")}</Link>
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

export function NewSupplierPage() {
  const t = useTranslations("purchasing.supplierForm");
  return (
    <>
      <BackLink />
      <PageHeader title={t("newTitle")} description={t("newDescription")} />
      <SupplierForm />
    </>
  );
}

export function SupplierPage({ supplierId }: { supplierId: string }) {
  const t = useTranslations("purchasing.supplierForm");
  const errors = useErrorText();
  const router = useRouter();
  const { can } = useAuth();
  const query = useSuppliersGet(supplierId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  const supplier = query.data.data;
  return (
    <>
      <BackLink />
      <PageHeader
        title={supplier.name}
        description={[supplier.code, supplier.city].filter(Boolean).join(" · ")}
        actions={
          can("purchasing.manage") ? (
            <ConfirmDialog
              destructive
              trigger={
                <Button variant="outline" className="min-h-10">
                  {t("delete")}
                </Button>
              }
              title={t("deleteTitle", { name: supplier.name })}
              description={t("deleteBody")}
              confirmLabel={t("delete")}
              onConfirm={async () => {
                try {
                  await suppliersDelete(supplier.id);
                  toast.success(t("deleted"));
                  router.replace("/manage/purchasing/suppliers");
                } catch (err) {
                  const fields = errors.fields(err);
                  toast.error(fields.supplier ?? errors.message(err));
                }
              }}
            />
          ) : null
        }
      />
      <div className="grid gap-6 xl:grid-cols-[1fr_24rem]">
        <SupplierForm key={supplier.updated_at} supplier={supplier} />
        <SupplierProductsCard supplierId={supplier.id} />
      </div>
    </>
  );
}

function SupplierProductsCard({ supplierId }: { supplierId: string }) {
  const t = useTranslations("purchasing.supplierProducts");
  const { can } = useAuth();
  const cursor = useCursor();
  const query = useSupplierProductsList(supplierId, { cursor: cursor.cursor, page_size: 20 });
  const page = query.data?.data;
  const rows = page?.results ?? [];
  const columns: DataTableColumn<SupplierProduct>[] = [
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <Link
          href={`/manage/products/${row.original.product_id}`}
          className="block hover:underline"
        >
          <span className="block font-medium">{row.original.product_name}</span>
          <span className="text-muted-foreground block text-xs">
            {row.original.product_code}
            {row.original.supplier_code
              ? ` · ${t("theirCode", { code: row.original.supplier_code })}`
              : ""}
          </span>
        </Link>
      ),
    },
    {
      id: "preferred",
      header: t("preferred"),
      cell: ({ row }) =>
        row.original.is_preferred ? <Badge variant="secondary">{t("preferred")}</Badge> : null,
    },
    {
      id: "pack",
      header: t("pack"),
      cell: ({ row }) =>
        row.original.pack_size ? <QtyText value={row.original.pack_size} /> : "—",
    },
    ...(can("costs.view")
      ? [
          {
            id: "lastCost",
            header: t("lastCost"),
            cell: ({ row }: { row: { original: SupplierProduct } }) =>
              row.original.last_unit_cost ? <MoneyText value={row.original.last_unit_cost} /> : "—",
          } satisfies DataTableColumn<SupplierProduct>,
        ]
      : []),
  ];
  return (
    <section className="space-y-3" aria-labelledby="supplier-products">
      <h2 id="supplier-products" className="font-semibold">
        {t("title")}
      </h2>
      <DataTable
        columns={columns}
        data={rows}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["pack", "lastCost"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={{ title: t("emptyTitle"), description: t("emptyBody") }}
        cardLayout={{
          product: "title",
          preferred: "primary",
          pack: "primary",
          lastCost: "primary",
        }}
      />
    </section>
  );
}
