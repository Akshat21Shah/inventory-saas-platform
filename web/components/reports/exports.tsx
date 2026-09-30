"use client";

import { Download, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import {
  reportRunsRetrieve,
  useReportRunsList,
} from "@/lib/api/generated/endpoints/reports/reports";
import type { ReportRun } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";

import { BackLink } from "./viewer";
import { useReportWords } from "./words";

const WORKING = new Set(["QUEUED", "RUNNING"]);

/** A fresh link at the moment of the tap (links last 5 minutes; the list may be older). */
function DownloadButton({ run }: { run: ReportRun }) {
  const t = useTranslations("reports.exports");
  const { message } = useErrorText();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="outline"
      className="min-h-10"
      disabled={busy}
      aria-label={t("downloadLabel", { name: run.file_name || run.title })}
      onClick={async () => {
        setBusy(true);
        try {
          const fresh = await reportRunsRetrieve(run.id);
          if (fresh.data.download_url) window.location.assign(fresh.data.download_url);
        } catch (error) {
          toast.error(message(error));
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy ? <Loader2 aria-hidden className="animate-spin" /> : <Download aria-hidden />}
      {t("download")}
    </Button>
  );
}

/** The files this person exported in the background ("Report ready" links here); refreshed
 * while one is still being made. */
export function MyExports() {
  const t = useTranslations("reports.exports");
  const words = useReportWords();
  const cursor = useCursor();
  const query = useReportRunsList(
    { cursor: cursor.cursor },
    {
      query: {
        refetchInterval: (q) =>
          q.state.data?.data.results.some((run) => WORKING.has(run.status)) ? 3_000 : false,
      },
    },
  );
  const columns: DataTableColumn<ReportRun>[] = [
    {
      id: "report",
      header: t("report"),
      cell: ({ row }) => (
        <span className="font-medium">
          {words.title(row.original.report_code, row.original.title)}
        </span>
      ),
    },
    {
      id: "asked",
      header: t("asked"),
      cell: ({ row }) => <DateText value={row.original.created_at} withTime />,
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => (
        <span className="flex flex-col gap-1">
          <StatusBadge status={row.original.status} labels="reportRunStatus" />
          {row.original.status === "FAILED" ? (
            <span className="text-muted-foreground text-xs">{t("failed")}</span>
          ) : null}
        </span>
      ),
    },
    {
      id: "rows",
      header: t("rows"),
      cell: ({ row }) => <span className="tabular-nums">{row.original.row_count ?? "—"}</span>,
    },
    {
      id: "until",
      header: t("until"),
      cell: ({ row }) =>
        row.original.expires_at ? <DateText value={row.original.expires_at} withTime /> : "—",
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) =>
        row.original.status === "READY" && row.original.download_url ? (
          <DownloadButton run={row.original} />
        ) : null,
    },
  ];
  return (
    <>
      <BackLink />
      <PageHeader title={t("title")} description={t("description")} />
      <DataTable
        columns={columns}
        data={query.data?.data.results ?? []}
        getRowId={(run) => run.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        empty={{ title: t("empty"), description: t("emptyBody") }}
        numericColumns={["rows"]}
        caption={t("caption")}
        cardLayout={{ report: "title", status: "primary", asked: "primary", rows: "primary" }}
        pagination={cursor.pagination(query.data?.data)}
      />
    </>
  );
}
