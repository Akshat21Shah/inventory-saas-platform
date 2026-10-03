"use client";

import { ChevronDown, ChevronRight, Headset } from "lucide-react";
import { useTranslations } from "@/lib/i18n/translations";
import { Fragment, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AuditLog } from "@/lib/api/generated/model";
import { useIsCompact } from "@/lib/use-media";

import { EmptyState } from "./empty-state";
import { ErrorState } from "./error-state";
import { DateText } from "./money-text";
import { TableSkeleton } from "./skeletons";

export const AUDIT_FILTERS = [
  "settings.",
  "staff.",
  "tenant.",
  "auth.",
  "impersonation.",
  "feature",
  "subscription.",
];

type Changes = Record<string, [unknown, unknown]>;

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Before/after for each changed field (spec 5.16). Secrets arrive already masked. */
export function DiffViewer({ changes }: { changes: unknown }) {
  const t = useTranslations("audit");
  const entries = Object.entries((changes as Changes | null) ?? {});
  if (entries.length === 0)
    return <p className="text-muted-foreground text-sm">{t("noChanges")}</p>;
  return (
    <dl className="grid grid-cols-[minmax(8rem,auto)_1fr_1fr] gap-x-4 gap-y-1 text-sm">
      <dt className="text-muted-foreground font-medium">{t("field")}</dt>
      <dd className="text-muted-foreground font-medium">{t("before")}</dd>
      <dd className="text-muted-foreground font-medium">{t("after")}</dd>
      {entries.map(([field, [before, after]]) => (
        <Fragment key={field}>
          <dt className="font-mono text-xs break-all">{field}</dt>
          <dd className="break-all">{show(before)}</dd>
          <dd className="break-all">{show(after)}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

function actionLabel(t: ReturnType<typeof useTranslations>, action: string): string {
  return t.has(`actions.${action}`) ? t(`actions.${action}`) : action;
}

const UUID_IN_TEXT = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

/** What was changed, in plain words: internal ids are replaced by the kind of record. */
function targetLabel(t: ReturnType<typeof useTranslations>, row: AuditLog): string {
  const repr = row.target_repr ?? "";
  if (repr && !UUID_IN_TEXT.test(repr)) return repr;
  const kind = (row.target_type ?? "").split(".").pop() ?? "";
  if (kind && t.has(`targets.${kind}`)) return t(`targets.${kind}`);
  return kind ? t("targets.other") : "—";
}

interface AuditTableProps {
  rows: AuditLog[];
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  filter: string;
  onFilterChange: (value: string) => void;
  showTenant?: boolean;
  pagination?: {
    hasNext: boolean;
    hasPrevious: boolean;
    onNext: () => void;
    onPrevious: () => void;
  };
}

/** The audit trail: who did what, when, with support sessions clearly marked (ADR-029). */
export function AuditTable({
  rows,
  isLoading,
  error,
  onRetry,
  filter,
  onFilterChange,
  showTenant,
  pagination,
}: AuditTableProps) {
  const t = useTranslations("audit");
  const tc = useTranslations("common");
  const [open, setOpen] = useState<string | null>(null);
  const compact = useIsCompact();

  const toolbar = (
    <div className="flex flex-wrap items-center gap-2 pb-4">
      <Select
        value={filter || "all"}
        onValueChange={(value) => onFilterChange(value === "all" ? "" : value)}
      >
        <SelectTrigger className="min-h-10 w-full sm:w-56" aria-label={t("action")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t("filterAll")}</SelectItem>
          {AUDIT_FILTERS.map((value) => (
            <SelectItem key={value} value={value}>
              {t(`filters.${value.replace(/\.$/, "")}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );

  let body;
  if (isLoading) body = <TableSkeleton columns={4} />;
  else if (error) body = <ErrorState error={error} onRetry={onRetry} />;
  else if (rows.length === 0)
    body = <EmptyState title={t("emptyTitle")} description={t("emptyBody")} />;
  else if (compact) {
    // Phones and tablets: one card per entry (CLAUDE.md "Responsive design").
    body = (
      <ul className="space-y-3">
        {rows.map((row) => {
          const expanded = open === row.id;
          const actor = row.actor;
          return (
            <li key={row.id} className="space-y-1 rounded-xl border p-3 text-sm">
              <p className="font-medium">{actionLabel(t, row.action)}</p>
              <p className="text-muted-foreground">
                <DateText value={row.created_at} withTime /> ·{" "}
                {actor ? actor.full_name || actor.email : t("system")}
                {showTenant && row.tenant ? ` · ${row.tenant.name}` : ""}
              </p>
              {row.impersonator ? (
                <p className="text-warning-strong flex items-center gap-1 text-xs">
                  <Headset aria-hidden className="size-3" />
                  {t("via", { name: row.impersonator.full_name || row.impersonator.email || "" })}
                </p>
              ) : null}
              <p className="break-words">{targetLabel(t, row)}</p>
              <Button
                variant="ghost"
                size="sm"
                className="-ml-2"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : row.id)}
              >
                {expanded ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
                {expanded ? t("hideDetails") : t("showDetails")}
              </Button>
              {expanded ? (
                <div className="bg-muted/40 space-y-3 rounded-lg p-3">
                  <DiffViewer changes={row.changes} />
                  {row.ip ? (
                    <p className="text-muted-foreground text-xs">{t("ip", { ip: row.ip })}</p>
                  ) : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    );
  } else {
    body = (
      <div className="overflow-x-auto rounded-xl border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead>{t("when")}</TableHead>
              <TableHead>{t("who")}</TableHead>
              <TableHead>{t("action")}</TableHead>
              <TableHead>{t("target")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const expanded = open === row.id;
              const actor = row.actor;
              return (
                <Fragment key={row.id}>
                  <TableRow>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-8"
                        aria-expanded={expanded}
                        aria-label={expanded ? t("hideDetails") : t("showDetails")}
                        onClick={() => setOpen(expanded ? null : row.id)}
                      >
                        {expanded ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
                      </Button>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <DateText value={row.created_at} withTime />
                    </TableCell>
                    <TableCell>
                      <span className="block">
                        {actor ? actor.full_name || actor.email : t("system")}
                      </span>
                      {row.impersonator ? (
                        <span className="text-warning-strong flex items-center gap-1 text-xs">
                          <Headset aria-hidden className="size-3" />
                          {t("via", {
                            name: row.impersonator.full_name || row.impersonator.email || "",
                          })}
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      {actionLabel(t, row.action)}
                      {showTenant && row.tenant ? (
                        <span className="text-muted-foreground block text-xs">
                          {row.tenant.name}
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell className="max-w-64 truncate">{targetLabel(t, row)}</TableCell>
                  </TableRow>
                  {expanded ? (
                    <TableRow>
                      <TableCell />
                      <TableCell colSpan={4} className="bg-muted/40 space-y-3 py-3">
                        <DiffViewer changes={row.changes} />
                        {row.ip ? (
                          <p className="text-muted-foreground text-xs">{t("ip", { ip: row.ip })}</p>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ) : null}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      </div>
    );
  }

  return (
    <div>
      {toolbar}
      {body}
      {pagination && !isLoading && !error ? (
        <div className="flex justify-end gap-2 pt-3">
          <Button
            variant="outline"
            disabled={!pagination.hasPrevious}
            onClick={pagination.onPrevious}
          >
            {tc("previous")}
          </Button>
          <Button variant="outline" disabled={!pagination.hasNext} onClick={pagination.onNext}>
            {tc("next")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
