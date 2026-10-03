"use client";

import { Pencil, Plus, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  platformCessTypesCreate,
  platformCessTypesUpdate,
  platformFeatureFlagsUpdate,
  platformHsnHintsCreate,
  platformHsnHintsDelete,
  platformHsnHintsImport,
  platformHsnHintsUpdate,
  platformPlansCreate,
  platformPlansUpdate,
  platformTaxRatesCreate,
  platformTaxRatesUpdate,
  usePlatformCessTypesList,
  usePlatformFeatureFlagsList,
  usePlatformHsnHintsList,
  usePlatformPlansList,
  usePlatformTaxRatesList,
} from "@/lib/api/generated/endpoints/platform/platform";
import type {
  CalcMethodEnum,
  CessType,
  FeatureFlag,
  HsnHint,
  Plan,
  TaxRate,
} from "@/lib/api/generated/model";
import { ApiError } from "@/lib/api/errors";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";

import {
  FieldsDialog,
  intOrNull,
  type FieldSpec,
  type FieldValue,
} from "@/components/shared/fields-dialog";
import { useTranslations } from "@/lib/i18n/translations";

const s = (value: FieldValue | undefined) => String(value ?? "").trim();

// --- Plans -----------------------------------------------------------------------------------

export function PlansPage() {
  const t = useTranslations("platform.plans");
  const tc = useTranslations("platform");
  const query = usePlatformPlansList();
  const limit = (value: number | null | undefined) => (value == null ? t("unlimited") : value);

  const fields = (editing: boolean): FieldSpec[] => [
    { name: "code", label: t("code"), required: true, readOnly: editing, hint: t("codeHint") },
    { name: "name", label: t("name"), required: true },
    { name: "price_monthly", label: t("price"), kind: "decimal" },
    { name: "max_retailers", label: t("maxRetailers"), kind: "int", hint: t("limitHint") },
    { name: "max_staff", label: t("maxStaff"), kind: "int", hint: t("limitHint") },
    { name: "max_products", label: t("maxProducts"), kind: "int", hint: t("limitHint") },
    { name: "is_default", label: t("isDefault"), kind: "bool" },
    { name: "is_active", label: t("isActive"), kind: "bool" },
  ];
  const toBody = (v: Record<string, FieldValue>) => ({
    name: s(v.name),
    price_monthly: s(v.price_monthly) || "0.00",
    max_retailers: intOrNull(v.max_retailers),
    max_staff: intOrNull(v.max_staff),
    max_products: intOrNull(v.max_products),
    is_default: Boolean(v.is_default),
    is_active: Boolean(v.is_active),
  });
  const initialOf = (plan?: Plan): Record<string, FieldValue> => ({
    code: plan?.code ?? "",
    name: plan?.name ?? "",
    price_monthly: plan?.price_monthly ?? "0.00",
    max_retailers: plan?.max_retailers == null ? "" : String(plan.max_retailers),
    max_staff: plan?.max_staff == null ? "" : String(plan.max_staff),
    max_products: plan?.max_products == null ? "" : String(plan.max_products),
    is_default: plan?.is_default ?? false,
    is_active: plan?.is_active ?? true,
  });

  const columns: DataTableColumn<Plan>[] = [
    {
      id: "name",
      header: t("name"),
      cell: ({ row }) => (
        <span className="flex flex-wrap items-center gap-2">
          {row.original.name}
          {row.original.is_default ? <Badge>{t("default")}</Badge> : null}
          {row.original.is_active === false ? (
            <Badge variant="secondary">{t("inactive")}</Badge>
          ) : null}
        </span>
      ),
    },
    { id: "code", header: t("code"), cell: ({ row }) => row.original.code },
    {
      id: "price",
      header: t("price"),
      cell: ({ row }) => <MoneyText value={row.original.price_monthly ?? "0"} />,
    },
    {
      id: "retailers",
      header: t("maxRetailers"),
      cell: ({ row }) => limit(row.original.max_retailers),
    },
    { id: "staff", header: t("maxStaff"), cell: ({ row }) => limit(row.original.max_staff) },
    {
      id: "products",
      header: t("maxProducts"),
      cell: ({ row }) => limit(row.original.max_products),
    },
    {
      id: "edit",
      header: "",
      cell: ({ row }) => (
        <FieldsDialog
          trigger={
            <Button
              variant="ghost"
              size="icon"
              className="size-10"
              aria-label={`${t("edit")}: ${row.original.name}`}
            >
              <Pencil aria-hidden />
            </Button>
          }
          title={t("edit")}
          fields={fields(true)}
          initial={initialOf(row.original)}
          submitLabel={tc("detail.saveChanges")}
          onSubmit={async (v) => {
            await platformPlansUpdate(row.original.id, toBody(v));
            toast.success(t("saved"));
            void query.refetch();
          }}
        />
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("body")}
        actions={
          <FieldsDialog
            trigger={
              <Button className="min-h-10">
                <Plus aria-hidden />
                {t("new")}
              </Button>
            }
            title={t("new")}
            fields={fields(false)}
            initial={initialOf()}
            submitLabel={t("create")}
            onSubmit={async (v) => {
              await platformPlansCreate({ code: s(v.code), ...toBody(v) });
              toast.success(t("saved"));
              void query.refetch();
            }}
          />
        }
      />
      <p className="bg-muted mb-4 rounded-lg p-3 text-sm">{t("enforcementOff")}</p>
      <DataTable
        columns={columns}
        data={query.data?.data ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
      />
    </>
  );
}

// --- Feature flags ---------------------------------------------------------------------------

export function FeatureFlagsPage() {
  const t = useTranslations("platform.flags");
  const errors = useErrorText();
  const query = usePlatformFeatureFlagsList();
  const [pending, setPending] = useState<string | null>(null);

  async function toggle(
    flag: FeatureFlag,
    field: "default_enabled" | "tenant_toggleable",
    value: boolean,
  ) {
    setPending(`${flag.code}:${field}`);
    try {
      await platformFeatureFlagsUpdate(flag.code, { [field]: value });
      await query.refetch();
    } catch (err) {
      toast.error(errors.message(err));
    } finally {
      setPending(null);
    }
  }

  const columns: DataTableColumn<FeatureFlag>[] = [
    {
      id: "name",
      header: t("module"),
      cell: ({ row }) => (
        <div>
          <p className="font-medium">{row.original.name}</p>
          <p className="text-muted-foreground text-xs">{row.original.description}</p>
        </div>
      ),
    },
    {
      id: "default",
      header: t("defaultOn"),
      cell: ({ row }) => (
        <Switch
          aria-label={`${t("defaultOn")}: ${row.original.name}`}
          checked={Boolean(row.original.default_enabled)}
          disabled={pending !== null}
          onCheckedChange={(v) => void toggle(row.original, "default_enabled", v)}
        />
      ),
    },
    {
      id: "toggleable",
      header: t("tenantToggleable"),
      cell: ({ row }) => (
        <Switch
          aria-label={`${t("tenantToggleable")}: ${row.original.name}`}
          checked={Boolean(row.original.tenant_toggleable)}
          disabled={pending !== null}
          onCheckedChange={(v) => void toggle(row.original, "tenant_toggleable", v)}
        />
      ),
    },
  ];

  return (
    <>
      <PageHeader title={t("title")} description={t("body")} />
      <DataTable
        columns={columns}
        data={query.data?.data ?? []}
        getRowId={(row) => row.code}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
      />
    </>
  );
}

// --- Tax masters -----------------------------------------------------------------------------

function RatesTab() {
  const t = useTranslations("platform.tax");
  const errors = useErrorText();
  const query = usePlatformTaxRatesList();
  const columns: DataTableColumn<TaxRate>[] = [
    { id: "rate", header: t("rate"), cell: ({ row }) => `${row.original.rate}%` },
    { id: "label", header: t("label"), cell: ({ row }) => row.original.label },
    { id: "notes", header: t("notes"), cell: ({ row }) => row.original.notes || "—" },
    {
      id: "active",
      header: t("active"),
      cell: ({ row }) => (
        <Switch
          aria-label={`${t("active")}: ${row.original.label}`}
          checked={row.original.is_active !== false}
          onCheckedChange={async (is_active) => {
            try {
              await platformTaxRatesUpdate(row.original.id, { is_active });
              void query.refetch();
            } catch (err) {
              toast.error(errors.message(err));
            }
          }}
        />
      ),
    },
  ];
  return (
    <DataTable
      columns={columns}
      data={query.data?.data ?? []}
      getRowId={(row) => row.id}
      isLoading={query.isLoading}
      error={query.error}
      onRetry={() => void query.refetch()}
      numericColumns={["rate"]}
      toolbar={
        <FieldsDialog
          trigger={
            <Button className="min-h-10">
              <Plus aria-hidden />
              {t("newRate")}
            </Button>
          }
          title={t("newRate")}
          description={t("rateHint")}
          fields={[
            { name: "rate", label: t("rate"), kind: "decimal", required: true },
            { name: "label", label: t("label"), required: true },
            { name: "notes", label: t("notes") },
          ]}
          initial={{ rate: "", label: "", notes: "" }}
          submitLabel={t("add")}
          onSubmit={async (v) => {
            await platformTaxRatesCreate({ rate: s(v.rate), label: s(v.label), notes: s(v.notes) });
            toast.success(t("saved"));
            void query.refetch();
          }}
        />
      }
    />
  );
}

function CessTab() {
  const t = useTranslations("platform.tax");
  const query = usePlatformCessTypesList();
  const methods = [
    { value: "PERCENT", label: t("methods.PERCENT") },
    { value: "SPECIFIC_PER_UNIT", label: t("methods.SPECIFIC_PER_UNIT") },
  ];
  const columns: DataTableColumn<CessType>[] = [
    { id: "code", header: t("code"), cell: ({ row }) => row.original.code },
    { id: "name", header: t("label"), cell: ({ row }) => row.original.name },
    {
      id: "method",
      header: t("method"),
      cell: ({ row }) => t(`methods.${row.original.calc_method ?? "PERCENT"}`),
    },
    {
      id: "active",
      header: t("active"),
      cell: ({ row }) => (row.original.is_active === false ? t("no") : t("yes")),
    },
    {
      id: "edit",
      header: "",
      cell: ({ row }) => (
        <FieldsDialog
          trigger={
            <Button
              variant="ghost"
              size="icon"
              className="size-10"
              aria-label={`${t("edit")}: ${row.original.name}`}
            >
              <Pencil aria-hidden />
            </Button>
          }
          title={t("edit")}
          fields={[
            { name: "code", label: t("code"), readOnly: true },
            { name: "name", label: t("label"), required: true },
            { name: "calc_method", label: t("method"), kind: "select", options: methods },
            { name: "is_active", label: t("active"), kind: "bool" },
          ]}
          initial={{
            code: row.original.code,
            name: row.original.name,
            calc_method: row.original.calc_method ?? "PERCENT",
            is_active: row.original.is_active !== false,
          }}
          submitLabel={t("save")}
          onSubmit={async (v) => {
            await platformCessTypesUpdate(row.original.id, {
              name: s(v.name),
              calc_method: s(v.calc_method) as CalcMethodEnum,
              is_active: Boolean(v.is_active),
            });
            void query.refetch();
          }}
        />
      ),
    },
  ];
  return (
    <DataTable
      columns={columns}
      data={query.data?.data ?? []}
      getRowId={(row) => row.id}
      isLoading={query.isLoading}
      error={query.error}
      onRetry={() => void query.refetch()}
      toolbar={
        <FieldsDialog
          trigger={
            <Button className="min-h-10">
              <Plus aria-hidden />
              {t("newCess")}
            </Button>
          }
          title={t("newCess")}
          fields={[
            { name: "code", label: t("code"), required: true },
            { name: "name", label: t("label"), required: true },
            { name: "calc_method", label: t("method"), kind: "select", options: methods },
          ]}
          initial={{ code: "", name: "", calc_method: "PERCENT" }}
          submitLabel={t("add")}
          onSubmit={async (v) => {
            await platformCessTypesCreate({
              code: s(v.code),
              name: s(v.name),
              calc_method: s(v.calc_method) as CalcMethodEnum,
            });
            void query.refetch();
          }}
        />
      }
    />
  );
}

function HsnTab() {
  const t = useTranslations("platform.tax");
  const errors = useErrorText();
  const cursor = useCursor();
  const [prefix, setPrefix] = useState("");
  const query = usePlatformHsnHintsList({ prefix: prefix || undefined, cursor: cursor.cursor });
  const page = query.data?.data;
  const fileInput = useRef<HTMLInputElement>(null);
  const [importErrors, setImportErrors] = useState<string[]>([]);

  async function importFile(file: File) {
    setImportErrors([]);
    try {
      const result = await platformHsnHintsImport({ file });
      toast.success(t("imported", { created: result.data.created, updated: result.data.updated }));
      void query.refetch();
    } catch (err) {
      const raw =
        err instanceof ApiError
          ? (err.details as { fields?: Record<string, unknown> }).fields?.file
          : undefined;
      if (Array.isArray(raw)) setImportErrors(raw.map(String));
      else toast.error(errors.message(err));
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const columns: DataTableColumn<HsnHint>[] = [
    { id: "prefix", header: t("hsnPrefix"), cell: ({ row }) => row.original.hsn_prefix },
    { id: "rate", header: t("rate"), cell: ({ row }) => `${row.original.gst_rate}%` },
    { id: "from", header: t("effectiveFrom"), cell: ({ row }) => row.original.effective_from },
    {
      id: "description",
      header: t("description"),
      cell: ({ row }) => row.original.description || "—",
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <div className="flex justify-end">
          <FieldsDialog
            trigger={
              <Button
                variant="ghost"
                size="icon"
                className="size-10"
                aria-label={`${t("edit")}: ${row.original.hsn_prefix}`}
              >
                <Pencil aria-hidden />
              </Button>
            }
            title={t("edit")}
            fields={[
              { name: "gst_rate", label: t("rate"), kind: "decimal", required: true },
              { name: "description", label: t("description") },
            ]}
            initial={{
              gst_rate: row.original.gst_rate,
              description: row.original.description ?? "",
            }}
            submitLabel={t("save")}
            onSubmit={async (v) => {
              await platformHsnHintsUpdate(row.original.id, {
                gst_rate: s(v.gst_rate),
                description: s(v.description),
              });
              void query.refetch();
            }}
          />
          <ConfirmDialog
            destructive
            trigger={
              <Button
                variant="ghost"
                size="icon"
                className="size-10"
                aria-label={`${t("delete")}: ${row.original.hsn_prefix}`}
              >
                <Trash2 aria-hidden />
              </Button>
            }
            title={t("deleteTitle", { prefix: row.original.hsn_prefix })}
            confirmLabel={t("delete")}
            onConfirm={async () => {
              await platformHsnHintsDelete(row.original.id);
              void query.refetch();
            }}
          />
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-sm">{t("hsnBody")}</p>
      {importErrors.length > 0 ? (
        <div
          role="alert"
          className="border-destructive/40 bg-destructive/5 rounded-lg border p-3 text-sm"
        >
          <p className="font-medium">{t("importFailed")}</p>
          <ul className="mt-1 list-disc pl-5">
            {importErrors.slice(0, 20).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        pagination={cursor.pagination(page)}
        empty={{ title: t("hsnEmpty") }}
        toolbar={
          <div className="flex flex-wrap items-center gap-2">
            <Input
              className="h-10 w-48"
              inputMode="numeric"
              placeholder={t("searchPrefix")}
              aria-label={t("searchPrefix")}
              value={prefix}
              onChange={(e) => {
                setPrefix(e.target.value.replace(/\D/g, ""));
                cursor.reset();
              }}
            />
            <FieldsDialog
              trigger={
                <Button className="min-h-10">
                  <Plus aria-hidden />
                  {t("newHint")}
                </Button>
              }
              title={t("newHint")}
              fields={[
                { name: "hsn_prefix", label: t("hsnPrefix"), kind: "int", required: true },
                { name: "gst_rate", label: t("rate"), kind: "decimal", required: true },
                { name: "effective_from", label: t("effectiveFrom"), kind: "date", required: true },
                { name: "description", label: t("description") },
              ]}
              initial={{ hsn_prefix: "", gst_rate: "", effective_from: "", description: "" }}
              submitLabel={t("add")}
              onSubmit={async (v) => {
                await platformHsnHintsCreate({
                  hsn_prefix: s(v.hsn_prefix),
                  gst_rate: s(v.gst_rate),
                  effective_from: s(v.effective_from),
                  description: s(v.description),
                });
                void query.refetch();
              }}
            />
            <input
              ref={fileInput}
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              aria-label={t("importCsv")}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void importFile(file);
              }}
            />
            <Button
              variant="outline"
              className="min-h-10"
              onClick={() => fileInput.current?.click()}
            >
              <Upload aria-hidden />
              {t("importCsv")}
            </Button>
          </div>
        }
      />
      <p className="text-muted-foreground text-xs">{t("csvFormat")}</p>
    </div>
  );
}

export function TaxMastersPage() {
  const t = useTranslations("platform.tax");
  return (
    <>
      <PageHeader title={t("title")} description={t("body")} />
      <Tabs defaultValue="rates">
        <TabsList className="mb-4">
          <TabsTrigger value="rates" className="min-h-9">
            {t("tabs.rates")}
          </TabsTrigger>
          <TabsTrigger value="cess" className="min-h-9">
            {t("tabs.cess")}
          </TabsTrigger>
          <TabsTrigger value="hsn" className="min-h-9">
            {t("tabs.hsn")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="rates">
          <RatesTab />
        </TabsContent>
        <TabsContent value="cess">
          <CessTab />
        </TabsContent>
        <TabsContent value="hsn">
          <HsnTab />
        </TabsContent>
      </Tabs>
    </>
  );
}
