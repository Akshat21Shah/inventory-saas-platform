"use client";

import { FolderPlus, Pencil, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FieldsDialog } from "@/components/shared/fields-dialog";
import { PageHeader } from "@/components/shared/page-header";
import { TableSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import {
  catalogBrandsCreate,
  catalogBrandsDelete,
  catalogBrandsUpdate,
  catalogCategoriesCreate,
  catalogCategoriesDelete,
  catalogCategoriesUpdate,
  catalogUnitsCreate,
  catalogUnitsUpdate,
  useCatalogBrandsList,
  useCatalogCategoriesTree,
  useCatalogUnitsList,
} from "@/lib/api/generated/endpoints/catalog/catalog";
import type { Brand, Unit } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";

import { asTree, type TreeNode } from "./options";

function IconButton({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Button variant="ghost" size="icon" className="size-10" aria-label={label} title={label}>
      {children}
    </Button>
  );
}

function CategoryRow({
  node,
  manage,
  onChanged,
}: {
  node: TreeNode;
  manage: boolean;
  onChanged: () => void;
}) {
  const t = useTranslations("catalog.categories");
  const errors = useErrorText();
  return (
    <li>
      <div className="flex min-h-12 items-center justify-between gap-2 border-b py-1">
        <span className="min-w-0 truncate" style={{ paddingLeft: `${(node.level - 1) * 1.5}rem` }}>
          <span className={node.level === 1 ? "font-medium" : undefined}>{node.name}</span>
        </span>
        {manage ? (
          <span className="flex shrink-0">
            {node.level < 3 ? (
              <FieldsDialog
                trigger={
                  <IconButton label={t("addUnder", { name: node.name })}>
                    <FolderPlus aria-hidden />
                  </IconButton>
                }
                title={t("addUnder", { name: node.name })}
                fields={[{ name: "name", label: t("name"), required: true }]}
                initial={{ name: "" }}
                submitLabel={t("add")}
                onSubmit={async (v) => {
                  await catalogCategoriesCreate({ name: String(v.name), parent_id: node.id });
                  onChanged();
                }}
              />
            ) : null}
            <FieldsDialog
              trigger={
                <IconButton label={t("edit", { name: node.name })}>
                  <Pencil aria-hidden />
                </IconButton>
              }
              title={t("edit", { name: node.name })}
              fields={[
                { name: "name", label: t("name"), required: true },
                { name: "sort_order", label: t("sortOrder"), kind: "int", hint: t("sortHint") },
              ]}
              initial={{ name: node.name, sort_order: String(node.sort_order ?? 0) }}
              submitLabel={t("save")}
              onSubmit={async (v) => {
                await catalogCategoriesUpdate(node.id, {
                  name: String(v.name),
                  sort_order: Number(v.sort_order || 0),
                });
                onChanged();
              }}
            />
            <ConfirmDialog
              destructive
              trigger={
                <IconButton label={t("delete", { name: node.name })}>
                  <Trash2 aria-hidden />
                </IconButton>
              }
              title={t("delete", { name: node.name })}
              description={t("deleteBody")}
              confirmLabel={t("deleteConfirm")}
              onConfirm={async () => {
                try {
                  await catalogCategoriesDelete(node.id);
                  onChanged();
                } catch (err) {
                  toast.error(errors.message(err));
                }
              }}
            />
          </span>
        ) : null}
      </div>
      {node.children.length ? (
        <ul>
          {asTree(node.children).map((child) => (
            <CategoryRow key={child.id} node={child} manage={manage} onChanged={onChanged} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function CategoriesPage() {
  const t = useTranslations("catalog.categories");
  const { can } = useAuth();
  const manage = can("products.manage");
  const query = useCatalogCategoriesTree();
  const tree = asTree(query.data?.data);
  const refresh = () => void query.refetch();
  const add = manage ? (
    <FieldsDialog
      trigger={
        <Button className="min-h-10">
          <Plus aria-hidden />
          {t("addTop")}
        </Button>
      }
      title={t("addTop")}
      fields={[{ name: "name", label: t("name"), required: true }]}
      initial={{ name: "" }}
      submitLabel={t("add")}
      onSubmit={async (v) => {
        await catalogCategoriesCreate({ name: String(v.name) });
        refresh();
      }}
    />
  ) : null;

  let body;
  if (query.isLoading) body = <TableSkeleton columns={2} />;
  else if (query.error) body = <ErrorState error={query.error} onRetry={refresh} />;
  else if (tree.length === 0)
    body = <EmptyState title={t("emptyTitle")} description={t("emptyBody")} action={add} />;
  else
    body = (
      <ul className="rounded-xl border px-4">
        {tree.map((node) => (
          <CategoryRow key={node.id} node={node} manage={manage} onChanged={refresh} />
        ))}
      </ul>
    );
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} actions={add} />
      {body}
    </>
  );
}

export function BrandsPage() {
  const t = useTranslations("catalog.brands");
  const errors = useErrorText();
  const { can } = useAuth();
  const manage = can("products.manage");
  const cursor = useCursor();
  const query = useCatalogBrandsList({ cursor: cursor.cursor });
  const page = query.data?.data;
  const refresh = () => void query.refetch();
  const columns: DataTableColumn<Brand>[] = [
    { id: "name", header: t("name"), cell: ({ row }) => row.original.name },
    {
      id: "actions",
      header: "",
      cell: ({ row }) =>
        manage ? (
          <span className="flex justify-end">
            <FieldsDialog
              trigger={
                <IconButton label={t("edit", { name: row.original.name })}>
                  <Pencil aria-hidden />
                </IconButton>
              }
              title={t("edit", { name: row.original.name })}
              fields={[{ name: "name", label: t("name"), required: true }]}
              initial={{ name: row.original.name }}
              submitLabel={t("save")}
              onSubmit={async (v) => {
                await catalogBrandsUpdate(row.original.id, { name: String(v.name) });
                refresh();
              }}
            />
            <ConfirmDialog
              destructive
              trigger={
                <IconButton label={t("delete", { name: row.original.name })}>
                  <Trash2 aria-hidden />
                </IconButton>
              }
              title={t("delete", { name: row.original.name })}
              confirmLabel={t("deleteConfirm")}
              onConfirm={async () => {
                try {
                  await catalogBrandsDelete(row.original.id);
                  refresh();
                } catch (err) {
                  toast.error(errors.message(err));
                }
              }}
            />
          </span>
        ) : null,
    },
  ];
  return (
    <>
      <PageHeader
        title={t("title")}
        actions={
          manage ? (
            <FieldsDialog
              trigger={
                <Button className="min-h-10">
                  <Plus aria-hidden />
                  {t("add")}
                </Button>
              }
              title={t("add")}
              fields={[{ name: "name", label: t("name"), required: true }]}
              initial={{ name: "" }}
              submitLabel={t("add")}
              onSubmit={async (v) => {
                await catalogBrandsCreate({ name: String(v.name) });
                refresh();
              }}
            />
          ) : null
        }
      />
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={refresh}
        pagination={cursor.pagination(page)}
        empty={{ title: t("emptyTitle"), description: t("emptyBody") }}
      />
    </>
  );
}

export function UnitsPage() {
  const t = useTranslations("catalog.units");
  const { can } = useAuth();
  const manage = can("products.manage");
  const cursor = useCursor();
  const query = useCatalogUnitsList({ cursor: cursor.cursor });
  const page = query.data?.data;
  const refresh = () => void query.refetch();
  const fields = [
    { name: "code", label: t("code"), required: true, hint: t("codeHint") },
    { name: "name", label: t("name"), required: true },
    { name: "uqc", label: t("uqc"), required: true, hint: t("uqcHint") },
    { name: "allows_decimal", label: t("allowsDecimal"), kind: "bool" as const },
    { name: "is_active", label: t("active"), kind: "bool" as const },
  ];
  const payload = (v: Record<string, string | boolean>) => ({
    code: String(v.code),
    name: String(v.name),
    uqc: String(v.uqc),
    allows_decimal: Boolean(v.allows_decimal),
    is_active: Boolean(v.is_active),
  });
  const columns: DataTableColumn<Unit>[] = [
    { id: "code", header: t("code"), cell: ({ row }) => row.original.code },
    { id: "name", header: t("name"), cell: ({ row }) => row.original.name },
    { id: "uqc", header: t("uqc"), cell: ({ row }) => row.original.uqc },
    {
      id: "decimal",
      header: t("allowsDecimal"),
      cell: ({ row }) => (row.original.allows_decimal ? t("yes") : t("no")),
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => (
        <StatusBadge status={row.original.is_active === false ? "INACTIVE" : "ACTIVE"} />
      ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) =>
        manage ? (
          <FieldsDialog
            trigger={
              <IconButton label={t("edit", { name: row.original.code })}>
                <Pencil aria-hidden />
              </IconButton>
            }
            title={t("edit", { name: row.original.code })}
            fields={fields}
            initial={{
              code: row.original.code,
              name: row.original.name,
              uqc: row.original.uqc,
              allows_decimal: Boolean(row.original.allows_decimal),
              is_active: row.original.is_active !== false,
            }}
            submitLabel={t("save")}
            onSubmit={async (v) => {
              await catalogUnitsUpdate(row.original.id, payload(v));
              refresh();
            }}
          />
        ) : null,
    },
  ];
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          manage ? (
            <FieldsDialog
              trigger={
                <Button className="min-h-10">
                  <Plus aria-hidden />
                  {t("add")}
                </Button>
              }
              title={t("add")}
              fields={fields}
              initial={{ code: "", name: "", uqc: "", allows_decimal: false, is_active: true }}
              submitLabel={t("add")}
              onSubmit={async (v) => {
                await catalogUnitsCreate(payload(v));
                refresh();
              }}
            />
          ) : null
        }
      />
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={refresh}
        pagination={cursor.pagination(page)}
      />
    </>
  );
}
