"use client";

import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";

import { AuditTable } from "@/components/shared/audit-table";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { RegistrySettingsForm } from "@/components/shared/registry-settings-form";
import { PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Input } from "@/components/ui/input";
import {
  platformSettingsUpdate,
  usePlatformAuditLogs,
  usePlatformImpersonationsList,
  usePlatformSettingsRegistry,
} from "@/lib/api/generated/endpoints/platform/platform";
import type { ImpersonationSession } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";

export function PlatformSettingsPage() {
  const t = useTranslations("platform.settingsPage");
  const query = usePlatformSettingsRegistry();
  return (
    <>
      <PageHeader title={t("title")} description={t("body")} />
      {query.isLoading ? (
        <PageSkeleton />
      ) : query.error || !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <RegistrySettingsForm
          rows={query.data.data}
          onSave={async (values) => (await platformSettingsUpdate({ values })).data}
          // Platform settings have no stored-row reset; putting the default back is the reset.
          onReset={async (key) => {
            const row = query.data.data.find((r) => r.key === key);
            return (await platformSettingsUpdate({ values: { [key]: row?.default } })).data;
          }}
        />
      )}
    </>
  );
}

export function PlatformAuditPage() {
  const t = useTranslations("audit");
  const [filter, setFilter] = useState("");
  const cursor = useCursor();
  const query = usePlatformAuditLogs({ action: filter || undefined, cursor: cursor.cursor });
  const page = query.data?.data;
  return (
    <>
      <PageHeader title={t("title")} description={t("platformBody")} />
      <AuditTable
        showTenant
        rows={page?.results ?? []}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        filter={filter}
        onFilterChange={(value) => {
          setFilter(value);
          cursor.reset();
        }}
        pagination={cursor.pagination(page)}
      />
    </>
  );
}

function sessionStatus(session: ImpersonationSession): string {
  if (session.ended_at) return "ENDED";
  return new Date(session.expires_at).getTime() < Date.now() ? "EXPIRED" : "ACTIVE";
}

export function ImpersonationsPage() {
  const t = useTranslations("platform.sessions");
  const [search, setSearch] = useState("");
  const cursor = useCursor();
  const query = usePlatformImpersonationsList({
    search: search || undefined,
    cursor: cursor.cursor,
  });
  const page = query.data?.data;
  const person = (p: ImpersonationSession["target"]) => p.full_name || p.email || p.phone || "—";
  const columns: DataTableColumn<ImpersonationSession>[] = [
    {
      id: "started",
      header: t("started"),
      cell: ({ row }) => <DateText value={row.original.created_at} withTime />,
    },
    { id: "by", header: t("by"), cell: ({ row }) => person(row.original.impersonator) },
    {
      id: "as",
      header: t("as"),
      cell: ({ row }) => (
        <span>
          {person(row.original.target)}
          <span className="text-muted-foreground block text-xs">{row.original.tenant.name}</span>
        </span>
      ),
    },
    {
      id: "reason",
      header: t("reason"),
      cell: ({ row }) => (
        <span className="block max-w-72">
          {row.original.reason}
          {row.original.act_reason ? (
            <span className="text-muted-foreground block text-xs">
              {t("actReason", { reason: row.original.act_reason })}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      id: "mode",
      header: t("mode"),
      cell: ({ row }) => t(`modes.${row.original.mode}`),
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => <StatusBadge status={sessionStatus(row.original)} />,
    },
  ];
  return (
    <>
      <PageHeader title={t("title")} description={t("body")} />
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        pagination={cursor.pagination(page)}
        empty={{ title: t("empty") }}
        toolbar={
          <Input
            className="h-10 w-full sm:w-72"
            type="search"
            placeholder={t("search")}
            aria-label={t("search")}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              cursor.reset();
            }}
          />
        }
      />
    </>
  );
}
