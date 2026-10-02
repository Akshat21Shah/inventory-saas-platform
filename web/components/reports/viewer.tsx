"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileSpreadsheet, FileText, Info, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getReportRunsListQueryKey,
  getReportsExportUrl,
  useReportsCatalogue,
  useReportsRun,
} from "@/lib/api/generated/endpoints/reports/reports";
import type {
  Column,
  Report,
  ReportPage,
  ReportRun,
  ReportsRunParams,
} from "@/lib/api/generated/model";
import { postForDownload } from "@/lib/api/download";
import { useErrorText } from "@/lib/api/use-error-text";

import { NUMERIC_KINDS, ReportLinkCell, ReportValue, type ReportRow } from "./cells";
import { ReportFilterBar, useReportFilters } from "./filters";
import { layoutFor } from "./layouts";
import { PeriodChart } from "./period-chart";
import { useReportWords, type ReportWords } from "./words";

type Row = ReportRow & { __row: string };

/** Back to the reports hub (44 px tall: a touch target on phones). */
export function BackLink() {
  const t = useTranslations("reports.viewer");
  return (
    <Link
      href="/manage/reports"
      className="text-muted-foreground hover:text-foreground mb-3 inline-flex min-h-11 items-center gap-1 text-sm"
    >
      <ArrowLeft aria-hidden className="size-4" />
      {t("back")}
    </Link>
  );
}

/** One report, from the catalogue's description of it (filters, columns): every report uses this
 * screen (ADR-050 item 1). */
export function ReportViewer({ code }: { code: string }) {
  const t = useTranslations("reports.viewer");
  const catalogue = useReportsCatalogue();
  const report = catalogue.data?.data.find((r) => r.code === code);
  if (catalogue.isLoading) return <PageSkeleton />;
  if (catalogue.error) {
    return <ErrorState error={catalogue.error} onRetry={() => void catalogue.refetch()} />;
  }
  if (!report) {
    return (
      <>
        <BackLink />
        <EmptyState title={t("notFound")} description={t("notFoundBody")} />
      </>
    );
  }
  return <ReportScreen key={report.code} report={report} />;
}

function useTableColumns(report: Report, page: ReportPage | undefined, words: ReportWords) {
  return useMemo(() => {
    const columns = page?.columns ?? report.columns;
    const { heading, slots } = layoutFor(report.code, columns);
    const table: DataTableColumn<Row>[] = columns.map((column) => ({
      id: column.key,
      header: words.column(report.code, column.key, column.label),
      cell: ({ row }) =>
        column.key === heading ? (
          <ReportLinkCell column={column} row={row.original} />
        ) : (
          <ReportValue column={column} value={row.original[column.key]} />
        ),
    }));
    return {
      table,
      numeric: columns.filter((c) => NUMERIC_KINDS.has(c.kind)).map((c) => c.key),
      layout: slots,
      columns,
    };
  }, [report, page, words]);
}

function ExportButtons({ report, filters }: { report: Report; filters: Record<string, string> }) {
  const t = useTranslations("reports.viewer");
  const { message } = useErrorText();
  const router = useRouter();
  const client = useQueryClient();
  const [busy, setBusy] = useState<"XLSX" | "PDF" | null>(null);
  const run = async (format: "XLSX" | "PDF") => {
    setBusy(format);
    try {
      const queued = await postForDownload<ReportRun>(
        getReportsExportUrl(report.code),
        { format, filters },
        `${report.code}.${format === "PDF" ? "pdf" : "xlsx"}`,
      );
      if (queued) {
        void client.invalidateQueries({ queryKey: getReportRunsListQueryKey() });
        toast.success(t("queued"), {
          action: {
            label: t("queuedAction"),
            onClick: () => router.push("/manage/reports/exports"),
          },
        });
      }
    } catch (error) {
      toast.error(message(error));
    } finally {
      setBusy(null);
    }
  };
  const icon = (format: "XLSX" | "PDF", Icon: typeof FileText) =>
    busy === format ? <Loader2 aria-hidden className="animate-spin" /> : <Icon aria-hidden />;
  return (
    <>
      <Button
        variant="outline"
        className="min-h-10"
        disabled={busy !== null}
        aria-label={t("exportExcelLabel")}
        onClick={() => void run("XLSX")}
      >
        {icon("XLSX", FileSpreadsheet)}
        {busy === "XLSX" ? t("preparing") : t("exportExcel")}
      </Button>
      {report.pdf ? (
        <Button
          variant="outline"
          className="min-h-10"
          disabled={busy !== null}
          aria-label={t("exportPdfLabel")}
          onClick={() => void run("PDF")}
        >
          {icon("PDF", FileText)}
          {busy === "PDF" ? t("preparing") : t("exportPdf")}
        </Button>
      ) : null}
    </>
  );
}

function Totals({
  report,
  columns,
  totals,
  words,
}: {
  report: Report;
  columns: Column[];
  totals: Record<string, unknown>;
  words: ReportWords;
}) {
  const t = useTranslations("reports.viewer");
  const shown = columns.filter((c) => c.total && c.key in totals);
  if (!shown.length) return null;
  return (
    <Card role="region" aria-labelledby="report-totals">
      <CardHeader className="pb-2">
        <CardTitle id="report-totals" className="text-base">
          {t("totals")}
        </CardTitle>
        <p className="text-muted-foreground text-xs">{t("totalsBody")}</p>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-4">
          {shown.map((c) => (
            <div key={c.key} className="min-w-0">
              <dt className="text-muted-foreground truncate text-xs">
                {words.column(report.code, c.key, c.label)}
              </dt>
              <dd className="text-lg font-semibold">
                <ReportValue column={c} value={totals[c.key]} />
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

function ReportScreen({ report }: { report: Report }) {
  const t = useTranslations("reports.viewer");
  const words = useReportWords();
  const { fields } = useErrorText();
  const filters = useReportFilters(report);
  const [page, setPage] = useState(1);
  const params = { ...filters.chosen, page } as ReportsRunParams;
  const query = useReportsRun(report.code, params, {
    query: { placeholderData: (previous) => previous },
  });
  const body = query.data?.data;
  const { table, numeric, layout, columns } = useTableColumns(report, body, words);
  const rows = useMemo<Row[]>(
    () => (body?.rows ?? []).map((row, index) => ({ ...row, __row: `${body?.page}-${index}` })),
    [body],
  );
  const pages = body ? Math.max(1, Math.ceil(body.count / body.page_size)) : 1;
  const title = words.title(report.code, report.title);
  const invalid = Object.entries(fields(query.error));
  return (
    <>
      <BackLink />
      <PageHeader
        title={title}
        description={words.description(report.code, report.description)}
        actions={<ExportButtons report={report} filters={filters.chosen} />}
      />
      <div className="space-y-4">
        <ReportFilterBar
          report={report}
          filters={filters}
          words={words}
          onChange={() => setPage(1)}
        />
        {invalid.length ? (
          <p role="alert" className="text-destructive text-sm">
            {invalid
              .map(([key, text]) => {
                const filter = report.filters.find((f) => f.key === key);
                return filter ? `${words.filter(key, filter.label)}: ${text}` : text;
              })
              .join(" ")}
          </p>
        ) : null}
        {report.own_shops || body?.own_shops ? (
          <p className="text-muted-foreground flex items-center gap-2 text-sm">
            <Info aria-hidden className="size-4 shrink-0" />
            {t("ownShops")}
          </p>
        ) : null}
        {report.background_only ? (
          <p className="text-muted-foreground flex items-center gap-2 text-sm">
            <Info aria-hidden className="size-4 shrink-0" />
            {t("backgroundOnly")}
          </p>
        ) : null}
        {report.code === "sales_summary" && rows.length > 1 ? (
          <PeriodChart
            rows={rows}
            labelKey="period"
            valueKey="total"
            caption={t("chartNetSales")}
          />
        ) : null}
        {body?.totals && body.rows.length ? (
          <Totals report={report} columns={columns} totals={body.totals} words={words} />
        ) : null}
        <DataTable
          columns={table}
          data={rows}
          getRowId={(row) => row.__row}
          isLoading={query.isLoading}
          error={invalid.length ? undefined : query.error}
          onRetry={() => void query.refetch()}
          empty={{ title: t("empty"), description: t("emptyBody") }}
          numericColumns={numeric}
          cardLayout={layout}
          caption={t("caption", { title })}
          toolbar={
            body ? (
              <span className="text-muted-foreground text-sm">
                {t("rows", { count: body.count })}
                {pages > 1 ? ` · ${t("page", { page: body.page, pages })}` : null}
              </span>
            ) : null
          }
          pagination={
            pages > 1
              ? {
                  hasNext: page < pages,
                  hasPrevious: page > 1,
                  onNext: () => setPage((p) => p + 1),
                  onPrevious: () => setPage((p) => Math.max(1, p - 1)),
                }
              : undefined
          }
        />
        {body?.notes.length ? (
          <section aria-labelledby="report-notes" className="space-y-1 text-sm">
            <h2 id="report-notes" className="font-medium">
              {t("notes")}
            </h2>
            <ul className="text-muted-foreground list-disc space-y-1 pl-5">
              {body.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </>
  );
}
