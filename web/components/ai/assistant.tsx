"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "@/lib/i18n/translations";
import { useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { ReportLinkCell, ReportValue, NUMERIC_KINDS } from "@/components/reports/cells";
import { reportHref } from "@/components/reports/hub";
import { layoutFor } from "@/components/reports/layouts";
import { useReportWords } from "@/components/reports/words";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton, PageSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  assistantAsk,
  getAssistantQuestionsListQueryKey,
  useAssistantQuestion,
  useAssistantQuestionsList,
  useAssistantTools,
} from "@/lib/api/generated/endpoints/assistant/assistant";
import type { AssistantQuestion, Column, Figures as FiguresData } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatDate, formatDateTime } from "@/lib/format";

type Row = Record<string, unknown>;

/** Suggested questions, each shown when its tool is one the person may use. */
const SUGGESTIONS: [tool: string, key: string][] = [
  ["shops_not_ordering", "notOrdering"],
  ["top_products", "topProducts"],
  ["sales_summary", "salesMonth"],
  ["low_stock", "lowStock"],
  ["dues", "dues"],
  ["collections", "collections"],
  ["backorders", "backorders"],
];

function Figures({ figures }: { figures: FiguresData }) {
  const t = useTranslations("assistant");
  const words = useReportWords();
  const { columns, layout, numeric } = useMemo(() => {
    const totals = figures.totals ?? {};
    const cols: Column[] = figures.columns.map((c) => ({
      ...c,
      cost: false,
      total: c.key in totals,
    }));
    const { heading, slots } = layoutFor(figures.report, cols);
    const table: DataTableColumn<Row>[] = cols.map((column) => ({
      id: column.key,
      header: words.column(figures.report, column.key, column.label),
      cell: ({ row }) =>
        column.key === heading ? (
          <ReportLinkCell column={column} row={row.original} />
        ) : (
          <ReportValue column={column} value={row.original[column.key]} />
        ),
    }));
    return {
      columns: table,
      layout: slots,
      numeric: cols.filter((c) => NUMERIC_KINDS.has(c.kind)).map((c) => c.key),
    };
  }, [figures, words]);
  const rows = useMemo(
    () => (figures.rows as Row[]).map((row, index) => ({ ...row, __row: index })),
    [figures.rows],
  );
  const title = words.title(figures.report, figures.title);
  const params = new URLSearchParams();
  if (figures.date_from) params.set("date_from", figures.date_from);
  if (figures.date_to) params.set("date_to", figures.date_to);
  const href = `${reportHref(figures.report)}${params.size ? `?${params}` : ""}`;
  return (
    <section aria-label={title} className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-medium">
          {title}
          {figures.date_from && figures.date_to ? (
            <span className="text-muted-foreground font-normal">
              {" "}
              ·{" "}
              {figures.date_from === figures.date_to
                ? formatDate(figures.date_from)
                : t("period", {
                    from: formatDate(figures.date_from),
                    to: formatDate(figures.date_to),
                  })}
            </span>
          ) : null}
        </h3>
        <Link
          href={href}
          className="text-primary text-sm underline-offset-4 hover:underline max-md:inline-flex max-md:min-h-11 max-md:min-w-11 max-md:items-center"
        >
          {t("openReport")}
        </Link>
      </div>
      {figures.own_shops ? <p className="text-muted-foreground text-sm">{t("ownShops")}</p> : null}
      <DataTable
        columns={columns}
        data={rows}
        getRowId={(row) => String(row.__row)}
        numericColumns={numeric}
        caption={title}
        empty={{ title: t("noRows") }}
        cardLayout={layout}
      />
      {figures.count > figures.rows.length ? (
        <p className="text-muted-foreground text-sm">
          {t("showing", { shown: figures.rows.length, count: figures.count })}
        </p>
      ) : null}
    </section>
  );
}

function Answer({ question }: { question: AssistantQuestion }) {
  const t = useTranslations("assistant");
  if (question.status === "PENDING") {
    return (
      <div role="status" aria-live="polite" className="space-y-2">
        <p className="text-muted-foreground text-sm">{t("thinking")}</p>
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    );
  }
  if (question.status === "FAILED") {
    return <p className="text-destructive text-sm">{t("failed")}</p>;
  }
  if (question.status === "LIMITED") {
    return <p className="text-destructive text-sm">{t("limited")}</p>;
  }
  const figures = question.tools.flatMap((call) => (call.ok && call.figures ? [call.figures] : []));
  return (
    <div className="space-y-6">
      <p className="whitespace-pre-line">{question.answer}</p>
      {figures.map((f, index) => (
        <Figures key={`${f.tool}-${index}`} figures={f} />
      ))}
    </div>
  );
}

/** One question and its answer; while it is being answered it checks every second. */
function QuestionCard({ initial }: { initial: AssistantQuestion }) {
  const t = useTranslations("assistant");
  const query = useAssistantQuestion(initial.id, {
    query: {
      enabled: initial.status === "PENDING",
      refetchInterval: (q) =>
        (q.state.data?.data.status ?? initial.status) === "PENDING" ? 1000 : false,
    },
  });
  const question = query.data?.data ?? initial;
  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4">
          <p className="font-semibold">{question.question}</p>
          <p className="text-muted-foreground text-xs">
            {t("askedAt", { when: formatDateTime(question.created_at) })}
          </p>
        </div>
        <Answer question={question} />
      </CardContent>
    </Card>
  );
}

/** Ask about the business's own figures (ADR-059). The server answers with the person's reports
 * (their permissions and shops); the page shows the answer and the figures it came from. */
export function Assistant() {
  const t = useTranslations("assistant");
  const errors = useErrorText();
  const client = useQueryClient();
  const tools = useAssistantTools();
  const history = useAssistantQuestionsList();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const available = new Set(tools.data?.data.tools.map((tool) => tool.name) ?? []);
  const questions = history.data?.data.results ?? [];

  async function send(question: string) {
    const trimmed = question.trim();
    if (trimmed.length < 3) return;
    setBusy(true);
    try {
      await assistantAsk({ question: trimmed });
      setText("");
      await client.invalidateQueries({ queryKey: getAssistantQuestionsListQueryKey() });
    } catch (err) {
      toast.error(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(text);
  }

  if (tools.isLoading) return <PageSkeleton />;
  if (tools.error) {
    return <ErrorState error={tools.error} onRetry={() => void tools.refetch()} />;
  }
  if (available.size === 0) {
    return (
      <>
        <PageHeader title={t("title")} description={t("body")} />
        <EmptyState title={t("nothingTitle")} description={t("nothingBody")} />
      </>
    );
  }
  return (
    <>
      <PageHeader title={t("title")} description={t("body")} />
      <div className="max-w-4xl space-y-6">
        <Card>
          <CardContent className="space-y-4 py-4">
            <form onSubmit={onSubmit} className="space-y-3">
              <Label htmlFor="assistant-question">{t("label")}</Label>
              <Textarea
                id="assistant-question"
                value={text}
                maxLength={500}
                rows={2}
                placeholder={t("placeholder")}
                onChange={(event) => setText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void send(text);
                  }
                }}
              />
              <div className="flex justify-end">
                <Button type="submit" disabled={busy || text.trim().length < 3}>
                  <Sparkles aria-hidden />
                  {t("ask")}
                </Button>
              </div>
            </form>
            <div className="space-y-2">
              <p className="text-muted-foreground text-sm">{t("try")}</p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.filter(([tool]) => available.has(tool)).map(([, key]) => (
                  <Button
                    key={key}
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    className="h-auto min-h-9 text-left whitespace-normal"
                    onClick={() => void send(t(`suggestions.${key}`))}
                  >
                    {t(`suggestions.${key}`)}
                  </Button>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
        <section aria-labelledby="assistant-history" className="space-y-3">
          <h2 id="assistant-history" className="text-lg font-semibold">
            {t("history")}
          </h2>
          {history.isLoading ? (
            <CardSkeleton />
          ) : history.error ? (
            <ErrorState error={history.error} onRetry={() => void history.refetch()} />
          ) : questions.length === 0 ? (
            <EmptyState title={t("noQuestions")} description={t("noQuestionsBody")} />
          ) : (
            <ul className="space-y-4">
              {questions.map((question) => (
                <li key={question.id}>
                  <QuestionCard initial={question} />
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
