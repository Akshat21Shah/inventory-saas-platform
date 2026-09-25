"use client";

import { tableFeatures, useTable, type ColumnDef, type RowData } from "@tanstack/react-table";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { EmptyState } from "./empty-state";
import { ErrorState } from "./error-state";
import { TableSkeleton } from "./skeletons";

const features = tableFeatures({});
export type DataTableColumn<TData extends RowData> = ColumnDef<typeof features, TData>;

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
}

/**
 * Server-driven table: rows arrive already filtered/sorted/paginated by the API (thin client).
 * Renders loading, empty and error states; scrolls horizontally inside its container on phones.
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
}: DataTableProps<TData>) {
  const t = useTranslations();
  const table = useTable({ features, columns, data, getRowId });
  const numeric = new Set(numericColumns);

  let body: ReactNode;
  if (isLoading) {
    body = <TableSkeleton columns={Math.min(columns.length, 6)} />;
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

  return (
    <div className="space-y-3">
      {toolbar ? <div className="flex flex-wrap items-center gap-2">{toolbar}</div> : null}
      {body}
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
