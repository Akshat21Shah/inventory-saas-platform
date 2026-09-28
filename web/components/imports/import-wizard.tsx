"use client";

import { CircleCheck, Download, FileSpreadsheet, Loader2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { DateText } from "@/components/shared/money-text";
import { ErrorState } from "@/components/shared/error-state";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getImportsReportUrl,
  getImportsTemplateUrl,
  importsCommit,
  importsCreate,
  useImportsList,
  useImportsRetrieve,
} from "@/lib/api/generated/endpoints/imports/imports";
import type {
  ImportJob,
  ImportJobList,
  ImportKindEnum,
  ImportModeEnum,
} from "@/lib/api/generated/model";
import { downloadFile } from "@/lib/api/download";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { cn } from "@/lib/utils";

/** The server's JSON for an import job's results (ADR-035). */
interface Counts {
  total?: number;
  new?: number;
  update?: number;
  unchanged?: number;
  error?: number;
  changes?: number;
  applied?: number;
  failed?: number;
}
interface RowError {
  row: number;
  key: string;
  messages: string[];
}
interface RowChange {
  row: number;
  key: string;
  action: "NEW" | "UPDATE";
  changes: Record<string, [unknown, unknown]>;
  highlight: string[];
  warnings: string[];
}

const KINDS: ImportKindEnum[] = [
  "PRODUCTS",
  "RETAILERS",
  "SPECIAL_PRICES",
  "PRICE_LIST_ITEMS",
  "DISCOUNT_RULES",
  "OPENING_STOCK",
];
// Records (products, shops, prices) are added or updated; stock is added to or set to a count
// (ADR-042). The server refuses a mode the kind doesn't offer.
const MODES: Partial<Record<ImportKindEnum, ImportModeEnum[]>> = {
  OPENING_STOCK: ["STOCK_ADD", "STOCK_SET"],
};
const RECORD_MODES: ImportModeEnum[] = ["ADD_ONLY", "ADD_OR_UPDATE"];
const PERMISSION: Record<ImportKindEnum, string> = {
  PRODUCTS: "products.manage",
  RETAILERS: "retailers.manage",
  SPECIAL_PRICES: "pricing.manage",
  PRICE_LIST_ITEMS: "pricing.manage",
  DISCOUNT_RULES: "pricing.manage",
  OPENING_STOCK: "stock.adjust",
  OPENING_BALANCES: "ledger.adjust",
};
const LIST_PAGE: Record<ImportKindEnum, string> = {
  PRODUCTS: "/manage/products",
  RETAILERS: "/manage/retailers",
  SPECIAL_PRICES: "/manage/pricing/special-prices",
  PRICE_LIST_ITEMS: "/manage/pricing/price-lists",
  DISCOUNT_RULES: "/manage/pricing/discounts",
  OPENING_STOCK: "/manage/stock",
  // TODO(phase-5 frontend): the receivables page once it exists.
  OPENING_BALANCES: "/manage/retailers",
};
const BUSY = new Set(["VALIDATING", "COMMITTING"]);

function Choice({
  name,
  value,
  checked,
  onChange,
  title,
  description,
  disabled,
}: {
  name: string;
  value: string;
  checked: boolean;
  onChange: (value: string) => void;
  title: string;
  description: string;
  disabled?: boolean;
}) {
  return (
    <label
      className={cn(
        "flex min-h-11 cursor-pointer gap-3 rounded-xl border p-4",
        checked ? "border-brand-400 bg-brand-50" : "hover:bg-muted",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <input
        type="radio"
        name={name}
        value={value}
        checked={checked}
        disabled={disabled}
        onChange={() => onChange(value)}
        className="accent-brand-600 mt-1 size-4"
      />
      <span>
        <span className="block font-medium">{title}</span>
        <span className="text-muted-foreground block text-sm">{description}</span>
      </span>
    </label>
  );
}

function Step({ number, title, children }: { number: number; title: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-3">
      <legend className="mb-3 flex items-center gap-2 font-semibold">
        <span className="bg-brand-600 flex size-6 items-center justify-center rounded-full text-xs text-white">
          {number}
        </span>
        {title}
      </legend>
      {children}
    </fieldset>
  );
}

export function ImportStartPage() {
  const t = useTranslations("imports");
  const errors = useErrorText();
  const router = useRouter();
  const params = useSearchParams();
  const { can } = useAuth();
  const allowed = KINDS.filter((k) => can(PERMISSION[k]));
  const requested = params.get("kind") as ImportKindEnum | null;
  const [kind, setKind] = useState<ImportKindEnum | "">(
    requested && allowed.includes(requested) ? requested : allowed.length === 1 ? allowed[0]! : "",
  );
  // No default: the distributor chooses the mode for every import (ADR-035).
  const [mode, setMode] = useState<ImportModeEnum | "">("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function start() {
    if (!kind || !mode || !file) return;
    setBusy(true);
    setError(null);
    try {
      const response = await importsCreate({ kind, mode, file });
      router.push(`/manage/imports/${response.data.id}`);
    } catch (err) {
      const fields = errors.fields(err);
      setError(fields.file ?? fields.mode ?? fields.kind ?? errors.message(err));
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Button asChild variant="outline" className="min-h-10">
            <Link href="/manage/imports">{t("pastImports")}</Link>
          </Button>
        }
      />
      <div className="max-w-2xl space-y-8">
        <Step number={1} title={t("whatTitle")}>
          <div className="grid gap-3 sm:grid-cols-2">
            {KINDS.map((k) => (
              <Choice
                key={k}
                name="kind"
                value={k}
                checked={kind === k}
                onChange={(v) => {
                  setKind(v as ImportKindEnum);
                  setMode("");
                }}
                title={t(`kind.${k}`)}
                description={t(`kindHint.${k}`)}
                disabled={!allowed.includes(k)}
              />
            ))}
          </div>
          {kind ? (
            <Button
              variant="link"
              className="h-auto p-0"
              onClick={() =>
                void downloadFile(
                  getImportsTemplateUrl(kind),
                  `${kind.toLowerCase()}-template.xlsx`,
                ).catch((err: unknown) => toast.error(errors.message(err)))
              }
            >
              <Download aria-hidden />
              {t("template", { kind: t(`kind.${kind}`) })}
            </Button>
          ) : null}
        </Step>
        <Step number={2} title={kind === "OPENING_STOCK" ? t("stockModeTitle") : t("modeTitle")}>
          <div className="grid gap-3">
            {((kind && MODES[kind]) || RECORD_MODES).map((value) => (
              <Choice
                key={value}
                name="mode"
                value={value}
                checked={mode === value}
                onChange={(v) => setMode(v as ImportModeEnum)}
                title={t(`mode.${value}`)}
                description={t(`modeHint.${value}`)}
              />
            ))}
          </div>
        </Step>
        <Step number={3} title={t("fileTitle")}>
          <label className="hover:bg-muted flex min-h-24 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed p-6 text-center">
            <FileSpreadsheet aria-hidden className="text-brand-700 size-8" />
            <span className="font-medium">{file ? file.name : t("chooseFile")}</span>
            <span className="text-muted-foreground text-sm">{t("fileHint")}</span>
            <input
              type="file"
              accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
              className="sr-only"
              aria-label={t("chooseFile")}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
        </Step>
        {error ? (
          <p role="alert" className="text-destructive text-sm font-medium">
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <Button
            className="min-h-11"
            disabled={!kind || !mode || !file || busy}
            onClick={() => void start()}
          >
            {busy ? <Loader2 aria-hidden className="animate-spin" /> : null}
            {t("check")}
          </Button>
          {!mode ? (
            <span className="text-muted-foreground text-sm">{t("chooseModeFirst")}</span>
          ) : null}
        </div>
        <p className="text-muted-foreground text-sm">{t("nothingSavedYet")}</p>
      </div>
    </>
  );
}

function CountCard({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className={cn("rounded-xl border p-4", tone)}>
      <p className="text-muted-foreground text-sm">{label}</p>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function show(value: unknown): string {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function ChangePreview({ changes }: { changes: RowChange[] }) {
  const t = useTranslations("imports");
  const updates = changes.filter((c) => c.action === "UPDATE");
  const added = changes.filter((c) => c.action === "NEW");
  return (
    <div className="space-y-6">
      {updates.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t("updatesTitle", { count: updates.length })}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="divide-y">
              {updates.map((change) => (
                <li key={change.row} className="space-y-1 py-3">
                  <p className="text-sm font-medium">
                    {change.key}{" "}
                    <span className="text-muted-foreground font-normal">
                      {t("rowNumber", { row: change.row })}
                    </span>
                  </p>
                  <ul className="space-y-1">
                    {Object.entries(change.changes).map(([field, [before, after]]) => {
                      const highlighted = change.highlight.includes(field);
                      return (
                        <li
                          key={field}
                          data-highlight={highlighted || undefined}
                          className={cn(
                            "flex flex-wrap items-center gap-x-2 rounded-md px-2 py-1 text-sm",
                            highlighted && "bg-warning/15",
                          )}
                        >
                          <span className="font-medium">{field}:</span>
                          <span className="text-muted-foreground line-through">{show(before)}</span>
                          <span aria-hidden>→</span>
                          <span className="sr-only">{t("changesTo")}</span>
                          <span className="font-medium">{show(after)}</span>
                          {highlighted ? <Badge variant="outline">{t("priceChange")}</Badge> : null}
                        </li>
                      );
                    })}
                  </ul>
                  {change.warnings.map((w) => (
                    <p key={w} className="text-warning-strong text-xs">
                      {w}
                    </p>
                  ))}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
      {added.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("newTitle", { count: added.length })}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-wrap gap-2">
              {added.map((change) => (
                <li key={change.row}>
                  <Badge variant="secondary">{change.key}</Badge>
                </li>
              ))}
            </ul>
            {added.some((c) => c.warnings.length) ? (
              <ul className="mt-3 space-y-1">
                {added.flatMap((c) =>
                  c.warnings.map((w) => (
                    <li key={`${c.row}-${w}`} className="text-warning-strong text-xs">
                      {t("rowNumber", { row: c.row })}: {w}
                    </li>
                  )),
                )}
              </ul>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function ErrorsList({ errors, title }: { errors: RowError[]; title: string }) {
  if (errors.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 text-sm">
          {errors.flatMap((e) =>
            e.messages.map((m) => (
              <li key={`${e.row}-${m}`} className="flex gap-2">
                <TriangleAlert aria-hidden className="text-destructive mt-0.5 size-4 shrink-0" />
                {m}
              </li>
            )),
          )}
        </ul>
      </CardContent>
    </Card>
  );
}

export function ImportJobPage({ jobId }: { jobId: string }) {
  const t = useTranslations("imports");
  const errorText = useErrorText();
  const query = useImportsRetrieve(jobId, {
    query: { refetchInterval: (q) => (BUSY.has(q.state.data?.data.status ?? "") ? 1500 : false) },
  });
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  const job: ImportJob = query.data.data;
  const counts = (job.counts ?? {}) as Counts;
  const rowErrors = (job.errors ?? []) as RowError[];
  const changes = (job.changes ?? []) as RowChange[];
  const notes = (job.notes ?? []) as string[];
  const report = () =>
    void downloadFile(getImportsReportUrl(job.id), "import-report.xlsx").catch((err: unknown) =>
      toast.error(errorText.message(err)),
    );

  const header = (
    <PageHeader
      title={t(`kind.${job.kind}`)}
      description={`${job.file_name} · ${t(`mode.${job.mode}`)}`}
      actions={
        job.status === "VALIDATED" || job.status === "COMMITTED" ? (
          <Button variant="outline" className="min-h-10" onClick={report}>
            <Download aria-hidden />
            {t("report")}
          </Button>
        ) : null
      }
    />
  );

  if (BUSY.has(job.status)) {
    return (
      <>
        {header}
        <div role="status" className="flex items-center gap-3 rounded-xl border p-6">
          <Loader2 aria-hidden className="text-brand-700 size-6 animate-spin" />
          <span>{job.status === "VALIDATING" ? t("checking") : t("importing")}</span>
        </div>
      </>
    );
  }
  if (job.status === "FAILED") {
    return (
      <>
        {header}
        <div role="alert" className="bg-destructive/10 space-y-3 rounded-xl p-6">
          <p className="font-medium">{t("failedTitle")}</p>
          <p className="text-sm">{job.problem}</p>
          <Button asChild variant="outline" className="min-h-10">
            <Link href={`/manage/imports/new?kind=${job.kind}`}>{t("tryAgain")}</Link>
          </Button>
        </div>
      </>
    );
  }
  if (job.status === "COMMITTED") {
    return (
      <>
        {header}
        <div role="status" className="bg-success/12 mb-6 flex gap-3 rounded-xl p-6">
          <CircleCheck aria-hidden className="text-success-strong size-6 shrink-0" />
          <div className="space-y-1">
            <p className="font-medium">{t("doneTitle", { count: counts.applied ?? 0 })}</p>
            {counts.failed ? (
              <p className="text-sm">{t("doneFailed", { count: counts.failed })}</p>
            ) : null}
          </div>
        </div>
        <ErrorsList errors={rowErrors} title={t("skippedRows")} />
        <Button asChild className="mt-6 min-h-11">
          <Link href={LIST_PAGE[job.kind]}>{t(`goTo.${job.kind}`)}</Link>
        </Button>
      </>
    );
  }

  // VALIDATED: nothing is saved yet; show what would change and ask to confirm.
  const toApply = counts.changes ?? 0;
  return (
    <>
      {header}
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <CountCard label={t("counts.new")} value={counts.new ?? 0} />
          <CountCard label={t("counts.update")} value={counts.update ?? 0} />
          <CountCard label={t("counts.unchanged")} value={counts.unchanged ?? 0} />
          <CountCard
            label={t("counts.error")}
            value={counts.error ?? 0}
            tone={counts.error ? "border-destructive/40 bg-destructive/5" : undefined}
          />
        </div>
        {notes.length ? (
          <ul className="text-muted-foreground list-disc space-y-1 pl-5 text-sm">
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        ) : null}
        <ErrorsList
          errors={rowErrors}
          title={t("errorsTitle", { count: counts.error ?? rowErrors.length })}
        />
        <ChangePreview changes={changes} />
        <div className="bg-muted/50 flex flex-col gap-3 rounded-xl p-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm">
            {toApply
              ? t("confirmSummary", { count: toApply, skipped: counts.error ?? 0 })
              : t("nothingToImport")}
          </p>
          <ConfirmDialog
            trigger={
              <Button className="min-h-11" disabled={!toApply}>
                {t("commit", { count: toApply })}
              </Button>
            }
            title={t("commitTitle", { count: toApply })}
            description={t("commitBody")}
            confirmLabel={t("commit", { count: toApply })}
            onConfirm={async () => {
              await importsCommit(job.id);
              void query.refetch();
            }}
          />
        </div>
      </div>
    </>
  );
}

export function ImportsPage() {
  const t = useTranslations("imports");
  const cursor = useCursor();
  const query = useImportsList({ cursor: cursor.cursor });
  const page = query.data?.data;
  const columns: DataTableColumn<ImportJobList>[] = [
    {
      id: "file",
      header: t("file"),
      cell: ({ row }) => (
        <Link href={`/manage/imports/${row.original.id}`} className="font-medium hover:underline">
          {row.original.file_name}
        </Link>
      ),
    },
    { id: "kind", header: t("what"), cell: ({ row }) => t(`kind.${row.original.kind}`) },
    { id: "mode", header: t("modeColumn"), cell: ({ row }) => t(`mode.${row.original.mode}`) },
    {
      id: "status",
      header: t("statusColumn"),
      cell: ({ row }) => <Badge variant="outline">{t(`status.${row.original.status}`)}</Badge>,
    },
    { id: "by", header: t("by"), cell: ({ row }) => row.original.created_by },
    {
      id: "when",
      header: t("when"),
      cell: ({ row }) => <DateText value={row.original.created_at} withTime />,
    },
  ];
  return (
    <>
      <PageHeader
        title={t("historyTitle")}
        actions={
          <Button asChild className="min-h-10">
            <Link href="/manage/imports/new">{t("newImport")}</Link>
          </Button>
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
        empty={{ title: t("historyEmpty") }}
      />
    </>
  );
}
