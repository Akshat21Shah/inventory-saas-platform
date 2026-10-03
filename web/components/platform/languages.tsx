"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Check, Download, RotateCcw, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { FormSelect } from "@/components/shared/form-select";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton } from "@/components/shared/skeletons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  getPlatformSettingsRegistryQueryKey,
  getPlatformTextsProgressQueryKey,
  getPlatformTextsSheetUrl,
  platformSettingsUpdate,
  platformTextSuggestionsUpdate,
  usePlatformSettingsRegistry,
  usePlatformTextSuggestionsList,
  usePlatformTextsProgress,
} from "@/lib/api/generated/endpoints/platform/platform";
import type {
  PlatformTextSuggestionsListStatus,
  Suggestion,
  TextProgress,
} from "@/lib/api/generated/model";
import { downloadFile } from "@/lib/api/download";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { languages } from "@/lib/i18n/config";
import { useTranslations } from "@/lib/i18n/translations";

const ENABLED = "platform.languages_enabled";
const TESTERS = "platform.language_test_tenants";
const STATUSES = ["NEW", "DONE", "DISMISSED"] as const;
const ALL = "all";

function listed(value: unknown): string[] {
  return String(value ?? "")
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

function useRefresh() {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: getPlatformSettingsRegistryQueryKey() }),
      client.invalidateQueries({ queryKey: getPlatformTextsProgressQueryKey() }),
    ]);
}

/** One language: on for everyone or not, and how far its review has got (ADR-060 item 12). */
function LanguageCard({ row, enabled }: { row: TextProgress; enabled: string[] }) {
  const t = useTranslations("platform.languages");
  const { message } = useErrorText();
  const refresh = useRefresh();
  const on = enabled.includes(row.code);
  const percent = (part: number) => (row.total ? Math.floor((part / row.total) * 100) : 0);
  const save = async (next: boolean) => {
    const codes = next ? [...enabled, row.code] : enabled.filter((code) => code !== row.code);
    try {
      await platformSettingsUpdate({
        values: { [ENABLED]: ["en", ...codes.filter((code) => code !== "en")].join(",") },
      });
      toast.success(t(next ? "turnedOn" : "turnedOff", { name: row.native }));
      await refresh();
    } catch (thrown) {
      toast.error(message(thrown));
      throw thrown;
    }
  };
  const id = `language-${row.code}`;
  return (
    <section className="space-y-3 rounded-xl border p-4" aria-labelledby={id}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={id} className="font-semibold">
          <span lang={row.code}>{row.native}</span>{" "}
          <span className="text-muted-foreground font-normal">({row.name})</span>
        </h2>
        <div className="flex min-h-11 items-center gap-2 text-sm">
          <ConfirmDialog
            trigger={<Switch checked={on} aria-label={t("onFor", { name: row.name })} />}
            title={t(on ? "turnOffTitle" : "turnOnTitle", { name: row.name })}
            description={
              on
                ? t("turnOffBody")
                : row.reviewed < row.total
                  ? t("turnOnUnreviewed", { reviewed: row.reviewed, total: row.total })
                  : t("turnOnBody")
            }
            confirmLabel={t(on ? "turnOff" : "turnOn")}
            destructive={on}
            onConfirm={() => save(!on)}
          />
          <span>{on ? t("on") : t("off")}</span>
        </div>
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-3">
        {(
          [
            ["translated", row.translated],
            ["reviewed", row.reviewed],
          ] as const
        ).map(([key, value]) => (
          <div key={key} className="space-y-1">
            <dt className="text-muted-foreground">{t(key)}</dt>
            <dd>
              {t("ofTotal", { count: value, total: row.total })}
              <span
                className="bg-muted mt-1 block h-2 overflow-hidden rounded-full"
                role="img"
                aria-label={t("percent", { percent: percent(value) })}
              >
                <span className="bg-primary block h-full" style={{ width: `${percent(value)}%` }} />
              </span>
            </dd>
          </div>
        ))}
        <div className="space-y-1">
          <dt className="text-muted-foreground">{t("newSuggestions")}</dt>
          <dd>{row.new_suggestions}</dd>
        </div>
      </dl>
    </section>
  );
}

/** The distributors whose staff and shops may use every language, to test them. */
function TestDistributors({ slugs }: { slugs: string[] }) {
  const t = useTranslations("platform.languages");
  const { message } = useErrorText();
  const refresh = useRefresh();
  const [adding, setAdding] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async (next: string[]) => {
    setBusy(true);
    try {
      await platformSettingsUpdate({ values: { [TESTERS]: next.join(",") } });
      await refresh();
      return true;
    } catch (thrown) {
      toast.error(message(thrown));
      return false;
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="space-y-3 rounded-xl border p-4" aria-labelledby="testers">
      <div className="space-y-1">
        <h2 id="testers" className="font-semibold">
          {t("testersTitle")}
        </h2>
        <p className="text-muted-foreground text-sm">{t("testersBody")}</p>
      </div>
      {slugs.length ? (
        <ul className="flex flex-wrap gap-2">
          {slugs.map((slug) => (
            <li key={slug}>
              <Badge variant="secondary" className="gap-1 py-1 pr-1 text-sm">
                {slug}
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8 max-md:size-11"
                  disabled={busy}
                  aria-label={t("removeTester", { slug })}
                  onClick={() => void save(slugs.filter((s) => s !== slug))}
                >
                  <X aria-hidden />
                </Button>
              </Badge>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground text-sm">{t("noTesters")}</p>
      )}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={async (event) => {
          event.preventDefault();
          const slug = adding.trim().toLowerCase();
          if (!slug || slugs.includes(slug)) return;
          if (await save([...slugs, slug])) setAdding("");
        }}
      >
        <div className="min-w-0 flex-1 space-y-1 sm:max-w-xs">
          <Label htmlFor="tester-slug">{t("addTester")}</Label>
          <Input
            id="tester-slug"
            className="h-10"
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            placeholder={t("addTesterPlaceholder")}
          />
        </div>
        <Button type="submit" variant="outline" className="min-h-10" disabled={busy}>
          {t("add")}
        </Button>
      </form>
    </section>
  );
}

/** The better words staff and shops suggested (ADR-060 item 14). */
function Suggestions() {
  const t = useTranslations("platform.languages");
  const { message } = useErrorText();
  const client = useQueryClient();
  const cursor = useCursor();
  const [status, setStatus] = useState<PlatformTextSuggestionsListStatus | typeof ALL>("NEW");
  const [language, setLanguage] = useState(ALL);
  const query = usePlatformTextSuggestionsList({
    status: status === ALL ? undefined : status,
    language: language === ALL ? undefined : language,
    cursor: cursor.cursor,
  });
  const page = query.data?.data;
  const settle = async (row: Suggestion, next: (typeof STATUSES)[number]) => {
    try {
      await platformTextSuggestionsUpdate(row.id, { status: next });
      toast.success(t(`settled.${next}`));
      await Promise.all([
        client.invalidateQueries({
          predicate: (q) =>
            String(q.queryKey[0] ?? "").startsWith("/api/v1/platform/texts/suggestions"),
        }),
        client.invalidateQueries({ queryKey: getPlatformTextsProgressQueryKey() }),
      ]);
    } catch (thrown) {
      toast.error(message(thrown));
    }
  };
  const native = (code: string) => languages.find((l) => l.code === code)?.native ?? code;
  const columns: DataTableColumn<Suggestion>[] = [
    {
      id: "words",
      header: t("words"),
      cell: ({ row }) => (
        <span className="block max-w-80 whitespace-normal" lang={row.original.language}>
          <span className="text-muted-foreground block line-through decoration-1">
            {row.original.current_text || "—"}
          </span>
          <span className="block font-medium break-words">{row.original.suggestion}</span>
        </span>
      ),
    },
    { id: "language", header: t("language"), cell: ({ row }) => native(row.original.language) },
    {
      id: "screen",
      header: t("screen"),
      cell: ({ row }) => <span className="font-mono text-xs break-all">{row.original.screen}</span>,
    },
    {
      id: "from",
      header: t("from"),
      cell: ({ row }) =>
        [row.original.tenant_name || t("platform"), row.original.sent_by]
          .filter(Boolean)
          .join(" · "),
    },
    {
      id: "when",
      header: t("when"),
      cell: ({ row }) => <DateText value={row.original.created_at} withTime />,
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => <Badge variant="outline">{t(`statuses.${row.original.status}`)}</Badge>,
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) =>
        row.original.status === "NEW" ? (
          <span className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              className="min-h-10 max-md:min-h-11"
              onClick={() => void settle(row.original, "DONE")}
            >
              <Check aria-hidden />
              {t("done")}
            </Button>
            <Button
              variant="ghost"
              className="min-h-10 max-md:min-h-11"
              onClick={() => void settle(row.original, "DISMISSED")}
            >
              {t("dismiss")}
            </Button>
          </span>
        ) : (
          <Button
            variant="ghost"
            className="min-h-10 max-md:min-h-11"
            onClick={() => void settle(row.original, "NEW")}
          >
            <RotateCcw aria-hidden />
            {t("reopen")}
          </Button>
        ),
    },
  ];
  const active = (status === "NEW" ? 0 : 1) + (language === ALL ? 0 : 1);
  return (
    <section className="space-y-3" aria-labelledby="suggestions">
      <div className="space-y-1">
        <h2 id="suggestions" className="text-lg font-semibold">
          {t("suggestionsTitle")}
        </h2>
        <p className="text-muted-foreground text-sm">{t("suggestionsBody")}</p>
      </div>
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        pagination={cursor.pagination(page)}
        caption={t("suggestionsTitle")}
        empty={{ title: t("noSuggestions") }}
        toolbar={
          <FilterBar
            active={active}
            onClear={() => {
              setStatus("NEW");
              setLanguage(ALL);
              cursor.reset();
            }}
            filters={
              <>
                <FormSelect
                  aria-label={t("status")}
                  value={status}
                  onValueChange={(value) => {
                    setStatus(value as typeof status);
                    cursor.reset();
                  }}
                  options={[
                    { value: ALL, label: t("allStatuses") },
                    ...STATUSES.map((s) => ({ value: s, label: t(`statuses.${s}`) })),
                  ]}
                />
                <FormSelect
                  aria-label={t("language")}
                  value={language}
                  onValueChange={(value) => {
                    setLanguage(value);
                    cursor.reset();
                  }}
                  options={[
                    { value: ALL, label: t("allLanguages") },
                    ...languages
                      .filter((l) => l.code !== "en")
                      .map((l) => ({ value: l.code, label: l.native })),
                  ]}
                />
              </>
            }
          />
        }
        cardLayout={{
          words: "title",
          language: "primary",
          from: "primary",
          status: "primary",
          screen: "secondary",
          when: "secondary",
          actions: "actions",
        }}
      />
    </section>
  );
}

/** Super admin → Languages: which languages everyone may use, the distributors testing the
 * others, each language's review, the translation sheet and the suggested words (ADR-060). */
export function PlatformLanguagesPage() {
  const t = useTranslations("platform.languages");
  const { message } = useErrorText();
  const registry = usePlatformSettingsRegistry();
  const progress = usePlatformTextsProgress();
  const [downloading, setDownloading] = useState(false);
  const rows = registry.data?.data ?? [];
  const enabled = listed(rows.find((row) => row.key === ENABLED)?.value);
  const testers = listed(rows.find((row) => row.key === TESTERS)?.value);
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("body")}
        actions={
          <Button
            variant="outline"
            className="min-h-10"
            disabled={downloading}
            onClick={async () => {
              setDownloading(true);
              try {
                await downloadFile(getPlatformTextsSheetUrl(), "texts.xlsx");
              } catch (thrown) {
                toast.error(message(thrown));
              } finally {
                setDownloading(false);
              }
            }}
          >
            <Download aria-hidden />
            {t("download")}
          </Button>
        }
      />
      <div className="space-y-8">
        {registry.isLoading || progress.isLoading ? (
          <CardSkeleton />
        ) : registry.error || progress.error ? (
          <ErrorState
            error={registry.error ?? progress.error}
            onRetry={() => {
              void registry.refetch();
              void progress.refetch();
            }}
          />
        ) : (
          <>
            <div className="space-y-3">
              <p className="text-muted-foreground text-sm">{t("englishAlwaysOn")}</p>
              {(progress.data?.data ?? []).map((row) => (
                <LanguageCard key={row.code} row={row} enabled={enabled} />
              ))}
            </div>
            <TestDistributors slugs={testers} />
          </>
        )}
        <Suggestions />
      </div>
    </>
  );
}
