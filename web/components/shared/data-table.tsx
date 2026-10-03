"use client";

import { tableFeatures, useTable, type ColumnDef, type RowData } from "@tanstack/react-table";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, ListChecks } from "lucide-react";
import { useTranslations } from "@/lib/i18n/translations";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useIsCompact } from "@/lib/use-media";
import { cn } from "@/lib/utils";

import { EmptyState } from "./empty-state";
import { ErrorState } from "./error-state";
import { TableSkeleton } from "./skeletons";

const features = tableFeatures({});
export type DataTableColumn<TData extends RowData> = ColumnDef<typeof features, TData>;

/**
 * Where a column goes when the list is shown as cards (phones and tablets, below 1024 px):
 * `title` (the card's heading, usually a link), `media` (a photo on the left), `primary` (label:
 * value lines always shown), `secondary` (behind "More"), `actions` (buttons at the card's right),
 * or `hidden`.
 */
export type CardSlot = "title" | "media" | "primary" | "secondary" | "actions" | "hidden";

/**
 * Header and cell templates are called as plain functions, not mounted as components: columns are
 * usually declared inline, and a new component type on every render would remount each cell
 * (losing focus and state in controls such as selects). So templates must not call hooks; put
 * stateful parts in their own components.
 */
function renderTemplate(template: unknown, context: unknown): ReactNode {
  return typeof template === "function"
    ? (template as (ctx: unknown) => ReactNode)(context)
    : (template as ReactNode);
}

interface CursorPagination {
  hasNext: boolean;
  hasPrevious: boolean;
  onNext: () => void;
  onPrevious: () => void;
}

export interface Selection<TData> {
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  /** Bulk action buttons, shown while rows are selected. */
  actions: ReactNode;
  /** Accessible names: "Select all products on this page", "Select Parle-G". */
  pageLabel: string;
  rowLabel: (row: TData) => string;
  /** Name of the bulk actions region. */
  regionLabel: string;
}

interface DataTableProps<TData extends RowData> {
  columns: DataTableColumn<TData>[];
  data: TData[];
  getRowId: (row: TData) => string;
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  empty?: { title: string; description?: string; action?: ReactNode };
  /** Column ids whose cells are numeric (money/qty): right-aligned per spec §8. */
  numericColumns?: string[];
  pagination?: CursorPagination;
  toolbar?: ReactNode;
  caption?: string;
  /** Card slot per column id. Without it: first column = title, a column without a heading (or
   * "actions") = actions, the next three = primary, the rest = secondary. With it, unlisted
   * columns are secondary (actions still go to actions). */
  cardLayout?: Partial<Record<string, CardSlot>>;
  selection?: Selection<TData>;
}

function slotsFor<TData extends RowData>(
  columns: DataTableColumn<TData>[],
  layout: Partial<Record<string, CardSlot>> | undefined,
): Record<string, CardSlot> {
  const slots: Record<string, CardSlot> = {};
  let primary = 0;
  columns.forEach((column, index) => {
    const id = String(column.id ?? index);
    // A column without a heading is the row's buttons.
    const isActions = id === "actions" || column.header === "";
    if (layout) slots[id] = layout[id] ?? (isActions ? "actions" : "secondary");
    else if (index === 0) slots[id] = "title";
    else if (isActions) slots[id] = "actions";
    else slots[id] = primary++ < 3 ? "primary" : "secondary";
  });
  return slots;
}

function toggle(set: Set<string>, id: string, on: boolean): Set<string> {
  const next = new Set(set);
  if (on) next.add(id);
  else next.delete(id);
  return next;
}

function BulkBar({
  count,
  label,
  actions,
  onClear,
  floating,
  onDone,
}: {
  count: number;
  label: string;
  actions: ReactNode;
  onClear: () => void;
  floating: boolean;
  onDone?: () => void;
}) {
  const t = useTranslations("table");
  return (
    <div
      role="region"
      aria-label={label}
      className={cn(
        "bg-brand-50 flex flex-wrap items-center gap-2 p-2",
        floating
          ? "fixed inset-x-0 bottom-0 z-40 max-h-[45dvh] overflow-y-auto border-t p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] shadow-lg"
          : "w-full rounded-lg",
      )}
    >
      <span className="text-sm font-medium">{t("selected", { count })}</span>
      {actions}
      <Button size="sm" variant="ghost" onClick={onClear}>
        {t("clearSelection")}
      </Button>
      {onDone ? (
        <Button size="sm" variant="outline" className="ml-auto" onClick={onDone}>
          {t("done")}
        </Button>
      ) : null}
    </div>
  );
}

/**
 * Server-driven table: rows arrive already filtered/sorted/paginated by the API (thin client).
 * Renders loading, empty and error states. Laptops get a table; phones and tablets get one card
 * per row (CLAUDE.md "Responsive design"), with selection through a "Select" mode and a bottom
 * action bar.
 */
export function DataTable<TData extends RowData>({
  columns,
  data,
  getRowId,
  isLoading,
  error,
  onRetry,
  empty,
  numericColumns = [],
  pagination,
  toolbar,
  caption,
  cardLayout,
  selection,
}: DataTableProps<TData>) {
  const t = useTranslations();
  const compact = useIsCompact();
  const [selecting, setSelecting] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const selectColumn: DataTableColumn<TData>[] = selection
    ? [
        {
          id: "__select",
          header: () => (
            <Checkbox
              aria-label={selection.pageLabel}
              checked={data.length > 0 && data.every((r) => selection.selected.has(getRowId(r)))}
              onCheckedChange={(checked) =>
                selection.onChange(checked ? new Set(data.map(getRowId)) : new Set())
              }
            />
          ),
          cell: ({ row }) => (
            <Checkbox
              aria-label={selection.rowLabel(row.original)}
              checked={selection.selected.has(getRowId(row.original))}
              onCheckedChange={(checked) =>
                selection.onChange(
                  toggle(selection.selected, getRowId(row.original), Boolean(checked)),
                )
              }
            />
          ),
        },
      ]
    : [];
  const table = useTable({ features, columns: [...selectColumn, ...columns], data, getRowId });
  const numeric = new Set(numericColumns);
  const slots = slotsFor(columns, cardLayout);
  const count = selection?.selected.size ?? 0;
  const clear = () => selection?.onChange(new Set());

  let body: ReactNode;
  if (isLoading) {
    body = <TableSkeleton columns={compact ? 2 : Math.min(columns.length, 6)} />;
  } else if (error) {
    body = <ErrorState error={error} onRetry={onRetry} />;
  } else if (data.length === 0) {
    body = (
      <EmptyState
        title={empty?.title ?? t("table.emptyTitle")}
        description={empty?.description ?? t("table.emptyBody")}
        action={empty?.action}
      />
    );
  } else if (compact) {
    body = (
      <ul className={cn("space-y-3", selecting && count > 0 && "pb-40")} aria-label={caption}>
        {table.getRowModel().rows.map((row) => {
          const cells = row.getAllCells().filter((c) => c.column.id !== "__select");
          const pick = (slot: CardSlot) => cells.filter((c) => slots[c.column.id] === slot);
          const label = (id: string) => {
            const header = columns.find((c) => String(c.id) === id)?.header;
            return typeof header === "string" ? header : "";
          };
          const fields = (list: typeof cells) => (
            <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
              {list.map((cell) => (
                <div key={cell.id} className="contents">
                  <dt className="text-muted-foreground">{label(cell.column.id)}</dt>
                  <dd className="min-w-0 break-words">
                    {renderTemplate(cell.column.columnDef.cell, cell.getContext())}
                  </dd>
                </div>
              ))}
            </dl>
          );
          const id = getRowId(row.original);
          const secondary = pick("secondary");
          const open = expanded.has(id);
          const checked = selection?.selected.has(id) ?? false;
          return (
            <li
              key={row.id}
              className={cn("rounded-xl border p-3", checked && "border-brand-400 bg-brand-50")}
            >
              <div className="flex gap-3">
                {selection && selecting ? (
                  <label className="-m-1 flex size-11 shrink-0 items-center justify-center">
                    <Checkbox
                      aria-label={selection.rowLabel(row.original)}
                      checked={checked}
                      onCheckedChange={(on) =>
                        selection.onChange(toggle(selection.selected, id, Boolean(on)))
                      }
                    />
                  </label>
                ) : null}
                {pick("media").map((cell) => (
                  <div key={cell.id} className="shrink-0">
                    {renderTemplate(cell.column.columnDef.cell, cell.getContext())}
                  </div>
                ))}
                <div className="min-w-0 flex-1 space-y-2">
                  {pick("title").map((cell) => (
                    <div key={cell.id} className="font-medium [&_a]:max-md:min-h-11">
                      {renderTemplate(cell.column.columnDef.cell, cell.getContext())}
                    </div>
                  ))}
                  {fields(pick("primary"))}
                </div>
                {pick("actions").map((cell) => (
                  <div key={cell.id} className="flex shrink-0 flex-col items-end gap-1">
                    {renderTemplate(cell.column.columnDef.cell, cell.getContext())}
                  </div>
                ))}
              </div>
              {secondary.length ? (
                <div className="mt-2">
                  {open ? <div className="border-t pt-2">{fields(secondary)}</div> : null}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="-ml-2"
                    aria-expanded={open}
                    onClick={() => setExpanded((all) => toggle(all, id, !open))}
                  >
                    {open ? <ChevronUp aria-hidden /> : <ChevronDown aria-hidden />}
                    {open ? t("table.less") : t("table.more")}
                  </Button>
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
          {caption ? <caption className="sr-only">{caption}</caption> : null}
          <TableHeader>
            {table.getHeaderGroups().map((group) => (
              <TableRow key={group.id}>
                {group.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    className={cn(numeric.has(header.column.id) && "text-right")}
                  >
                    {header.isPlaceholder
                      ? null
                      : renderTemplate(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getAllCells().map((cell) => (
                  <TableCell
                    key={cell.id}
                    className={cn(numeric.has(cell.column.id) && "text-right tabular-nums")}
                  >
                    {renderTemplate(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    );
  }

  const showSelectToggle = Boolean(selection && compact && data.length > 0 && !isLoading);
  return (
    <div className="space-y-3">
      {toolbar || showSelectToggle ? (
        <div className="flex flex-wrap items-center gap-2">
          {toolbar}
          {showSelectToggle ? (
            <Button
              variant={selecting ? "default" : "outline"}
              className="min-h-10"
              aria-pressed={selecting}
              onClick={() => {
                if (selecting) clear();
                setSelecting(!selecting);
              }}
            >
              <ListChecks aria-hidden />
              {selecting ? t("table.done") : t("table.select")}
            </Button>
          ) : null}
        </div>
      ) : null}
      {selection && count > 0 && !compact ? (
        <BulkBar
          count={count}
          label={selection.regionLabel}
          actions={selection.actions}
          onClear={clear}
          floating={false}
        />
      ) : null}
      {selection && selecting && compact ? (
        <p className="text-muted-foreground text-sm">{t("table.selectHint")}</p>
      ) : null}
      {body}
      {selection && count > 0 && compact ? (
        <BulkBar
          count={count}
          label={selection.regionLabel}
          actions={selection.actions}
          onClear={clear}
          floating
          onDone={() => {
            clear();
            setSelecting(false);
          }}
        />
      ) : null}
      {pagination && !isLoading && !error && data.length > 0 ? (
        <nav className="flex justify-end gap-2" aria-label={t("table.rowsLabel")}>
          <Button
            variant="outline"
            size="lg"
            disabled={!pagination.hasPrevious}
            onClick={pagination.onPrevious}
          >
            <ChevronLeft aria-hidden />
            {t("common.previous")}
          </Button>
          <Button
            variant="outline"
            size="lg"
            disabled={!pagination.hasNext}
            onClick={pagination.onNext}
          >
            {t("common.next")}
            <ChevronRight aria-hidden />
          </Button>
        </nav>
      ) : null}
    </div>
  );
}
