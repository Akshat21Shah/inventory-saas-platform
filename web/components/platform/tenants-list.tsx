"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePlatformTenantsList } from "@/lib/api/generated/endpoints/platform/platform";
import type { PlatformTenantsListStatus, TenantList } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useTranslations } from "@/lib/i18n/translations";

const STATUSES = ["ACTIVE", "ONBOARDING", "SUSPENDED"] as const;

export function TenantsList() {
  const t = useTranslations("platform.tenants");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [status, setStatus] = useState<string>("");
  const cursor = useCursor();
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  const query = usePlatformTenantsList({
    search: debounced || undefined,
    status: (status || undefined) as PlatformTenantsListStatus | undefined,
    cursor: cursor.cursor,
  });
  const page = query.data?.data;

  const columns: DataTableColumn<TenantList>[] = [
    {
      id: "name",
      header: t("name"),
      cell: ({ row }) => (
        <Link
          href={`/platform/tenants/${row.original.id}`}
          className="text-primary font-medium hover:underline"
        >
          {row.original.name}
        </Link>
      ),
    },
    {
      id: "slug",
      header: t("slug"),
      cell: ({ row }) => <span className="font-mono text-sm">{row.original.slug}</span>,
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => <StatusBadge status={row.original.status} />,
    },
    {
      id: "gstin",
      header: t("gstin"),
      cell: ({ row }) => <span className="font-mono text-sm">{row.original.gstin}</span>,
    },
    { id: "city", header: t("city"), cell: ({ row }) => row.original.city ?? "—" },
    { id: "plan", header: t("plan"), cell: ({ row }) => row.original.plan.name ?? "—" },
    {
      id: "created",
      header: t("created"),
      cell: ({ row }) => <DateText value={row.original.created_at} />,
    },
  ];

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("body")}
        actions={
          <Button asChild className="min-h-10">
            <Link href="/platform/tenants/new">
              <Plus aria-hidden />
              {t("new")}
            </Link>
          </Button>
        }
      />
      <DataTable
        columns={columns}
        cardLayout={{
          name: "title",
          status: "primary",
          slug: "primary",
          plan: "primary",
          gstin: "secondary",
          city: "secondary",
          created: "secondary",
        }}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={{ title: t("emptyTitle"), description: t("emptyBody") }}
        toolbar={
          <div className="flex flex-wrap gap-2">
            <Input
              type="search"
              placeholder={t("searchPlaceholder")}
              aria-label={t("searchPlaceholder")}
              className="h-10 w-full sm:w-72"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                cursor.reset();
              }}
            />
            <Select
              value={status || "all"}
              onValueChange={(value) => {
                setStatus(value === "all" ? "" : value);
                cursor.reset();
              }}
            >
              <SelectTrigger className="min-h-10 w-full sm:w-48" aria-label={t("status")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("allStatuses")}</SelectItem>
                {STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>
                    {t(`statuses.${s}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        }
      />
    </>
  );
}
