"use client";

import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "@/lib/i18n/translations";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { useSupplierOptions } from "@/components/purchasing/options";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { QtyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  planningStatsRefresh,
  reorderSuggestionsApplyLevels,
  reorderSuggestionsCreateOrders,
  reorderSuggestionsUpdate,
  useReorderSuggestionsList,
} from "@/lib/api/generated/endpoints/planning/planning";
import type { ReorderSuggestion } from "@/lib/api/generated/model";
import { ApiError } from "@/lib/api/errors";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatQty } from "@/lib/format";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";
import { useDebounced } from "@/lib/use-debounced";
import { useIsPhone } from "@/lib/use-media";

import { useDemandRate, useStockLasts } from "./words";

const ALL = "all";
// Whole numbers come whole from the server; units that can be split show at most 2 decimals.
const q = (value: string | null | undefined) => formatQty(value ?? "0", 2);

/** The server's figures in plain words (ADR-053 item 8): why this product, and why this much. */
export function Explanation({ row }: { row: ReorderSuggestion }) {
  const t = useTranslations("planning.why");
  const rate = useDemandRate();
  const unit = row.unit_code;
  const waiting = { waiting: q(row.waiting), unit, hasWaiting: String(Number(row.waiting) > 0) };
  const parts: string[] = [];
  if (row.basis === "DEMAND") {
    parts.push(
      t("demand", {
        demand: q(row.demand_qty),
        days: row.demand_days,
        rate: rate(row.demand_rate, unit),
        unit,
      }),
    );
  } else {
    // Older sales but no order lately, or never sold at all.
    parts.push(
      row.last_sale_date ? t("noRecentOrders", { days: row.demand_days }) : t("lowHistory"),
    );
  }
  parts.push(
    t("position", {
      available: q(row.available),
      onOrder: q(row.on_order),
      hasOnOrder: String(Number(row.on_order) > 0),
      ...waiting,
    }),
  );
  if (row.basis === "DEMAND") {
    parts.push(
      t("point", {
        point: q(row.reorder_point),
        lead: row.lead_days,
        source: t(`lead.${row.lead_source}`),
        safety: row.safety_days,
        unit,
      }),
    );
    parts.push(t("cover", { cover: row.cover_days, ...waiting }));
  } else if (Number(row.reorder_level) > 0) {
    parts.push(t("upToLevel", { level: q(row.reorder_level), ...waiting }));
  } else {
    parts.push(t("waitingOnly", waiting));
  }
  if (row.pack_size) parts.push(t("pack", { pack: q(row.pack_size), unit }));
  return <p className="text-muted-foreground text-xs leading-relaxed">{parts.join(" ")}</p>;
}

/** The action and how urgent it is: "Order 150 PCS (15 packs of 10) · about 10 days of stock
 * left", "Order 810 PCS (81 packs of 10) · out of stock, 297 PCS waiting". */
export function Headline({ row }: { row: ReorderSuggestion }) {
  const t = useTranslations("planning.headline");
  const unit = row.unit_code;
  const action =
    row.packs && row.pack_size
      ? t("orderPacks", { qty: q(row.to_order), unit, packs: row.packs, pack: q(row.pack_size) })
      : t("order", { qty: q(row.to_order), unit });
  const urgency: string[] = [];
  if (Number(row.available) <= 0) urgency.push(t("outOfStock"));
  else if (row.days_left !== null) {
    const days = Number(row.days_left);
    urgency.push(days < 1 ? t("lessThanDay") : t("daysLeft", { count: days }));
  } else if (Number(row.reorder_level) > 0 && Number(row.available) <= Number(row.reorder_level)) {
    urgency.push(t("atLevel"));
  }
  if (Number(row.waiting) > 0) urgency.push(t("waiting", { qty: q(row.waiting), unit }));
  return (
    <p className="font-medium">
      {urgency.length ? t("line", { action, urgency: urgency.join(", ") }) : action}
    </p>
  );
}

function QuantityCell({
  row,
  canChange,
  onChanged,
}: {
  row: ReorderSuggestion;
  canChange: boolean;
  onChanged: () => void;
}) {
  const t = useTranslations("planning.suggestions");
  const errors = useErrorText();
  const [value, setValue] = useState(String(Number(row.to_order)));
  if (!canChange) {
    return (
      <span className="whitespace-nowrap">
        <QtyText value={row.to_order} /> {row.unit_code}
      </span>
    );
  }
  async function save() {
    const typed = value.trim();
    const next = typed && Number(typed) !== Number(row.suggested_qty) ? typed : null;
    if ((next ?? null) === (row.quantity === null ? null : String(Number(row.quantity)))) return;
    try {
      await reorderSuggestionsUpdate(row.id, { quantity: next });
      onChanged();
    } catch (err) {
      toast.error(errors.fields(err).quantity ?? errors.message(err));
      setValue(String(Number(row.to_order)));
    }
  }
  return (
    <span className="flex items-center gap-2">
      <Input
        inputMode="decimal"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => void save()}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
        aria-label={t("quantityFor", { name: row.product_name, unit: row.unit_code })}
        className="h-11 w-24 text-right tabular-nums md:h-9"
      />
      <span className="text-muted-foreground text-xs">{row.unit_code}</span>
      {row.quantity !== null ? (
        <span className="text-muted-foreground text-xs">
          {t("suggested", { qty: q(row.suggested_qty) })}
        </span>
      ) : null}
    </span>
  );
}

function DismissDialog({ row, onDone }: { row: ReorderSuggestion; onDone: () => void }) {
  const t = useTranslations("planning.suggestions");
  const errors = useErrorText();
  const [open, setOpen] = useState(false);
  const [until, setUntil] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setUntil("");
          setError(null);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="ghost" className="min-h-9">
          {t("dismiss")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("dismissTitle", { name: row.product_name })}</DialogTitle>
          <DialogDescription>{t("dismissBody")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor={`until-${row.id}`}>{t("until")}</Label>
          <Input
            id={`until-${row.id}`}
            type="date"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
            className="h-11"
          />
        </div>
        {error ? (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          <Button variant="outline" className="min-h-11" onClick={() => setOpen(false)}>
            {t("keep")}
          </Button>
          <Button
            className="min-h-11"
            onClick={async () => {
              try {
                await reorderSuggestionsUpdate(row.id, { dismiss: true, until: until || null });
                toast.success(t("dismissed"));
                setOpen(false);
                onDone();
              } catch (err) {
                setError(errors.fields(err).until ?? errors.message(err));
              }
            }}
          >
            {t("dismiss")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function SuggestionsPage() {
  const t = useTranslations("planning.suggestions");
  const notSelling = useTranslations("planning.notSelling");
  const errors = useErrorText();
  const { can, feature } = useAuth();
  const purchasing = feature("purchasing");
  const manage = can("purchasing.manage");
  const showSuppliers = purchasing && can("purchasing.view");
  const levels = can("products.manage") || can("stock.adjust");
  const suppliers = useSupplierOptions(showSuppliers);
  const [search, setSearch] = useState("");
  const [basis, setBasis] = useState(ALL);
  const [supplier, setSupplier] = useState(ALL);
  // To order, or kept apart: below the reorder level but not selling (final review).
  const [show, setShow] = useState<"OPEN" | "NOT_SELLING">("OPEN");
  const apart = show === "NOT_SELLING";
  const phone = useIsPhone();
  const stockLasts = useStockLasts();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const ordersKey = useRef(newIdempotencyKey());
  const cursor = useCursor();
  const debounced = useDebounced(search.trim());
  const query = useReorderSuggestionsList(
    {
      cursor: cursor.cursor,
      search: debounced || undefined,
      basis: basis === ALL ? undefined : (basis as ReorderSuggestion["basis"]),
      supplier: supplier === ALL ? undefined : supplier,
      status: show,
    },
    { query: { enabled: feature("stock_planning") } },
  );
  const page = query.data?.data;
  const rows = page?.results ?? [];
  const refetch = () => void query.refetch();

  if (!feature("stock_planning")) {
    return <EmptyState title={t("offTitle")} description={t("offBody")} />;
  }

  async function refresh() {
    try {
      await planningStatsRefresh();
      toast.success(t("refreshing"));
    } catch (err) {
      toast.error(
        err instanceof ApiError && err.code === "RATE_LIMITED"
          ? t("refreshTooSoon")
          : errors.message(err),
      );
    }
  }

  async function createOrders() {
    try {
      const response = await reorderSuggestionsCreateOrders(
        { suggestion_ids: [...selected] },
        idempotent(ordersKey.current),
      );
      ordersKey.current = newIdempotencyKey();
      toast.success(
        t("ordersCreated", {
          count: response.data.length,
          numbers: response.data.map((o) => o.number).join(", "),
        }),
      );
      setSelected(new Set());
      refetch();
    } catch (err) {
      toast.error(errors.fields(err).suggestion_ids ?? errors.message(err));
    }
  }

  async function applyLevels() {
    try {
      const response = await reorderSuggestionsApplyLevels({ suggestion_ids: [...selected] });
      toast.success(t("levelsApplied", { count: response.data.changed }));
      setSelected(new Set());
    } catch (err) {
      toast.error(errors.message(err));
    }
  }

  const name = (row: ReorderSuggestion) => (
    <Link href={`/manage/products/${row.product_id}`} className="block hover:underline">
      <span className="block font-medium">{row.product_name}</span>
      <span className="text-muted-foreground block text-xs">{row.product_code}</span>
    </Link>
  );

  const apartColumns: DataTableColumn<ReorderSuggestion>[] = [
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <div className="max-w-xl space-y-1 whitespace-normal lg:min-w-64">
          {name(row.original)}
          <p className="text-sm">{notSelling("note")}</p>
          <p className="text-muted-foreground text-xs">
            {t("apartFigures", {
              available: q(row.original.available),
              level: q(row.original.reorder_level),
              unit: row.original.unit_code,
            })}
          </p>
        </div>
      ),
    },
    {
      id: "actions",
      header: t("actions"),
      cell: ({ row }) => (
        <Button asChild size="sm" variant="outline" className="min-h-9">
          <Link href={`/manage/stock/${row.original.product_id}`}>{t("changeLevel")}</Link>
        </Button>
      ),
    },
  ];

  const columns: DataTableColumn<ReorderSuggestion>[] = [
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <div className="max-w-xl space-y-1 whitespace-normal lg:min-w-64">
          {name(row.original)}
          <Headline row={row.original} />
          {phone ? (
            <details className="group">
              <summary className="text-primary flex min-h-11 cursor-pointer items-center text-xs">
                {t("why")}
              </summary>
              <Explanation row={row.original} />
            </details>
          ) : (
            <Explanation row={row.original} />
          )}
        </div>
      ),
    },
    {
      id: "left",
      header: t("daysLeft"),
      cell: ({ row }) => {
        const lasts = stockLasts(row.original.available, row.original.days_left);
        if (Number(row.original.available) <= 0) {
          return <Badge variant="destructive">{lasts}</Badge>;
        }
        if (lasts) return <span className="tabular-nums">{lasts}</span>;
        return Number(row.original.waiting) > 0 ? (
          <Badge variant="destructive">{t("shopsWaiting")}</Badge>
        ) : (
          <Badge variant="outline">{t("atLevel")}</Badge>
        );
      },
    },
    ...(showSuppliers
      ? [
          {
            id: "supplier",
            header: t("supplier"),
            cell: ({ row }: { row: { original: ReorderSuggestion } }) =>
              row.original.supplier_name ?? (
                <span className="text-muted-foreground">{t("noSupplier")}</span>
              ),
          } satisfies DataTableColumn<ReorderSuggestion>,
        ]
      : []),
    {
      id: "order",
      header: t("toOrder"),
      cell: ({ row }) => <QuantityCell row={row.original} canChange={manage} onChanged={refetch} />,
    },
    ...(manage
      ? [
          {
            id: "actions",
            header: t("actions"),
            cell: ({ row }: { row: { original: ReorderSuggestion } }) => (
              <DismissDialog row={row.original} onDone={refetch} />
            ),
          } satisfies DataTableColumn<ReorderSuggestion>,
        ]
      : []),
  ];

  const bulk = !apart && ((purchasing && manage) || levels);
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          manage ? (
            <Button variant="outline" className="min-h-10" onClick={() => void refresh()}>
              <RefreshCw aria-hidden />
              {t("refresh")}
            </Button>
          ) : null
        }
      />
      <DataTable
        columns={apart ? apartColumns : columns}
        data={rows}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={refetch}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={
          debounced || basis !== ALL || supplier !== ALL
            ? { title: t("noMatchTitle"), description: t("noMatchBody") }
            : apart
              ? { title: t("apartEmptyTitle"), description: t("apartEmptyBody") }
              : { title: t("emptyTitle"), description: t("emptyBody") }
        }
        cardLayout={
          apart
            ? { product: "title", actions: "actions" }
            : {
                product: "title",
                left: "primary",
                supplier: "primary",
                order: "primary",
                actions: "actions",
              }
        }
        selection={
          bulk
            ? {
                selected,
                onChange: setSelected,
                pageLabel: t("selectPage"),
                rowLabel: (row) => t("selectRow", { name: row.product_name }),
                regionLabel: t("bulkLabel"),
                actions: (
                  <>
                    {purchasing && manage ? (
                      <Button size="sm" onClick={() => void createOrders()}>
                        {t("createOrders")}
                      </Button>
                    ) : null}
                    {levels ? (
                      <Button size="sm" variant="outline" onClick={() => void applyLevels()}>
                        {t("useAsLevels")}
                      </Button>
                    ) : null}
                  </>
                ),
              }
            : undefined
        }
        toolbar={
          <FilterBar
            active={[basis, supplier].filter((f) => f !== ALL).length + (apart ? 1 : 0)}
            onClear={() => {
              setBasis(ALL);
              setSupplier(ALL);
              setShow("OPEN");
              setSelected(new Set());
              cursor.reset();
            }}
            search={
              <Input
                type="search"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  cursor.reset();
                }}
                placeholder={t("searchPlaceholder")}
                aria-label={t("search")}
                className="h-10 w-full sm:w-64"
              />
            }
            filters={
              <>
                <FilterSelect
                  label={t("show")}
                  value={show}
                  onChange={(value) => {
                    setShow(value as "OPEN" | "NOT_SELLING");
                    setSelected(new Set());
                    cursor.reset();
                  }}
                  options={[
                    { value: "OPEN", label: t("shows.OPEN") },
                    { value: "NOT_SELLING", label: t("shows.NOT_SELLING") },
                  ]}
                />
                <FilterSelect
                  label={t("basis")}
                  value={basis}
                  onChange={(value) => {
                    setBasis(value);
                    cursor.reset();
                  }}
                  options={[
                    { value: ALL, label: t("anyBasis") },
                    { value: "DEMAND", label: t("bases.DEMAND") },
                    { value: "LOW_HISTORY", label: t("bases.LOW_HISTORY") },
                  ]}
                />
                {showSuppliers ? (
                  <FilterSelect
                    label={t("supplier")}
                    value={supplier}
                    onChange={(value) => {
                      setSupplier(value);
                      cursor.reset();
                    }}
                    options={[{ value: ALL, label: t("anySupplier") }, ...suppliers]}
                  />
                ) : null}
              </>
            }
          />
        }
      />
    </>
  );
}
