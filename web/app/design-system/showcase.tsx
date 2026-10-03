"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Trash2 } from "lucide-react";
import { useTranslations } from "@/lib/i18n/translations";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FormField } from "@/components/shared/form-field";
import { DateText, MoneyText, QtyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton, TableSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/errors";
import { brandStyleSheet, DEFAULT_BRAND_COLOR } from "@/lib/theme/palette";

const STATUSES = [
  "PLACED",
  "ON_HOLD",
  "ACCEPTED",
  "PACKED",
  "DISPATCHED",
  "DELIVERED",
  "COMPLETED",
  "REJECTED",
  "CANCELLED",
  "IN_STOCK",
  "LOW_STOCK",
  "BACKORDER",
];
const BRAND_SWATCHES = ["#2f5bea", "#0f766e", "#b45309", "#be123c", "#7c3aed", "#15803d"];
const SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];

interface SampleRow {
  id: string;
  product: string;
  qty: string;
  price: string;
  status: string;
  date: string;
}

const SAMPLE_ROWS: SampleRow[] = [
  {
    id: "1",
    product: "Basmati Rice 5 kg",
    qty: "24",
    price: "1380.00",
    status: "PLACED",
    date: "2026-09-24T05:30:00Z",
  },
  {
    id: "2",
    product: "Sunflower Oil 1 L",
    qty: "120",
    price: "18450.50",
    status: "ON_HOLD",
    date: "2026-09-23T10:15:00Z",
  },
  {
    id: "3",
    product: "Turmeric Powder 200 g",
    qty: "2.750",
    price: "495.00",
    status: "DELIVERED",
    date: "2026-09-20T18:45:00Z",
  },
];
const EMPTY_ROWS: SampleRow[] = [];

type TableMode = "data" | "loading" | "empty" | "error";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2 className="text-lg font-semibold">{title}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  );
}

export function DesignSystemShowcase() {
  const t = useTranslations("designSystem");
  const [brand, setBrand] = useState(DEFAULT_BRAND_COLOR);
  const [tableMode, setTableMode] = useState<TableMode>("data");

  const columns = useMemo<DataTableColumn<SampleRow>[]>(
    () => [
      { id: "product", header: t("colProduct"), accessorKey: "product" },
      { id: "qty", header: t("colQty"), cell: ({ row }) => <QtyText value={row.original.qty} /> },
      {
        id: "price",
        header: t("colPrice"),
        cell: ({ row }) => <MoneyText value={row.original.price} />,
      },
      {
        id: "status",
        header: t("colStatus"),
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: "date",
        header: t("colDate"),
        cell: ({ row }) => <DateText value={row.original.date} />,
      },
    ],
    [t],
  );

  const schema = useMemo(
    () =>
      z.object({
        shopName: z.string().trim().min(1, t("shopNameRequired")),
        mobile: z.string().optional(),
      }),
    [t],
  );
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { shopName: "", mobile: "" },
  });

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <style>{brandStyleSheet(brand)}</style>
      <PageHeader title={t("title")} description={t("description")} />

      <Section title={t("brand")}>
        <p className="text-muted-foreground text-sm">{t("brandHint")}</p>
        <div className="flex flex-wrap items-center gap-2">
          {BRAND_SWATCHES.map((swatch) => (
            <button
              key={swatch}
              type="button"
              aria-label={swatch}
              aria-pressed={brand === swatch}
              onClick={() => setBrand(swatch)}
              className="size-11 rounded-full ring-offset-2 aria-pressed:ring-2 aria-pressed:ring-current"
              style={{ backgroundColor: swatch }}
            />
          ))}
          <Input
            aria-label={t("brand")}
            type="color"
            value={brand}
            onChange={(event) => setBrand(event.target.value)}
            className="h-11 w-16 p-1"
          />
        </div>
        <div className="grid grid-cols-6 gap-2 sm:grid-cols-11" aria-label={t("tokens")}>
          {SHADES.map((shade) => (
            <div key={shade} className="space-y-1 text-center text-xs">
              <div
                className="h-10 rounded-md border"
                style={{ background: `var(--brand-${shade})` }}
              />
              {shade}
            </div>
          ))}
        </div>
      </Section>

      <Section title={t("typography")}>
        <h1 className="text-3xl font-semibold tracking-tight">{t("sampleHeading")} 1</h1>
        <h2 className="text-2xl font-semibold tracking-tight">{t("sampleHeading")} 2</h2>
        <h3 className="text-lg font-semibold">{t("sampleHeading")} 3</h3>
        <p>{t("sampleBody")}</p>
        <p className="text-muted-foreground text-sm">{t("sampleBody")}</p>
      </Section>

      <Section title={t("buttons")}>
        <div className="flex flex-wrap gap-2">
          <Button size="lg">{t("primary")}</Button>
          <Button size="lg" variant="secondary">
            {t("secondary")}
          </Button>
          <Button size="lg" variant="outline">
            {t("outline")}
          </Button>
          <Button size="lg" variant="ghost">
            {t("ghost")}
          </Button>
          <Button size="lg" disabled>
            {t("primary")}
          </Button>
          <Button size="touch">{t("primary")} · 44px</Button>
        </div>
      </Section>

      <Section title={t("badges")}>
        <div className="flex flex-wrap gap-2">
          {STATUSES.map((status) => (
            <StatusBadge key={status} status={status} />
          ))}
        </div>
      </Section>

      <Section title={t("numbers")}>
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <dt className="text-muted-foreground">₹ (en-IN)</dt>
          <dd>
            <MoneyText value="123456.5" /> · <MoneyText value="0.01" /> ·{" "}
            <MoneyText value="-250.00" />
          </dd>
          <dt className="text-muted-foreground">{t("colQty")}</dt>
          <dd>
            <QtyText value="1234.500" /> · <QtyText value="2.750" unit="kg" />
          </dd>
          <dt className="text-muted-foreground">{t("colDate")}</dt>
          <dd>
            <DateText value="2026-03-31T19:00:00Z" /> ·{" "}
            <DateText value="2026-03-31T19:00:00Z" withTime />
          </dd>
        </dl>
      </Section>

      <Section title={t("states")}>
        <div className="grid gap-4 md:grid-cols-3">
          <CardSkeleton />
          <EmptyState title={t("showEmpty")} description={t("sampleBody")} />
          <ErrorState
            error={new ApiError(503, { code: "INTERNAL_ERROR", message: "", details: {} })}
            onRetry={() => undefined}
          />
        </div>
        <TableSkeleton rows={3} columns={4} />
      </Section>

      <Section title={t("table")}>
        <div className="flex flex-wrap gap-2" role="group" aria-label={t("table")}>
          {(["data", "loading", "empty", "error"] as const).map((mode) => (
            <Button
              key={mode}
              variant={tableMode === mode ? "default" : "outline"}
              aria-pressed={tableMode === mode}
              onClick={() => setTableMode(mode)}
            >
              {t(`show${mode[0]!.toUpperCase()}${mode.slice(1)}` as "showData")}
            </Button>
          ))}
        </div>
        <DataTable
          columns={columns}
          data={tableMode === "data" ? SAMPLE_ROWS : EMPTY_ROWS}
          getRowId={(row) => row.id}
          isLoading={tableMode === "loading"}
          error={tableMode === "error" ? new TypeError("fetch failed") : undefined}
          onRetry={() => setTableMode("data")}
          numericColumns={["qty", "price"]}
          caption={t("table")}
          pagination={{
            hasNext: true,
            hasPrevious: false,
            onNext: () => undefined,
            onPrevious: () => undefined,
          }}
        />
      </Section>

      <Section title={t("form")}>
        <form
          noValidate
          className="grid max-w-md gap-4"
          onSubmit={form.handleSubmit(() => toast.success(t("saved")))}
        >
          <FormField
            label={t("shopName")}
            hint={t("shopNameHint")}
            error={form.formState.errors.shopName?.message}
            required
          >
            <Input {...form.register("shopName")} className="h-11" />
          </FormField>
          <FormField label={t("mobile")}>
            <Input
              {...form.register("mobile")}
              inputMode="tel"
              autoComplete="tel"
              className="h-11"
            />
          </FormField>
          <Button type="submit" size="lg" className="w-fit">
            {t("save")}
          </Button>
        </form>
      </Section>

      <Section title={t("dialogs")}>
        <ConfirmDialog
          trigger={
            <Button variant="destructive" size="lg">
              <Trash2 aria-hidden />
              {t("destructive")}
            </Button>
          }
          title={t("deleteTitle")}
          description={t("deleteBody")}
          confirmLabel={t("destructive")}
          destructive
          onConfirm={() => {
            toast.success(t("deleted"));
          }}
        />
      </Section>
    </main>
  );
}
