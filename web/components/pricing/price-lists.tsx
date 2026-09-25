"use client";

import { ArrowLeft, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { WarningList } from "@/components/catalog/product-editor";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { FieldsDialog } from "@/components/shared/fields-dialog";
import { FormField } from "@/components/shared/form-field";
import { MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  priceListItemsDelete,
  priceListItemsUpsert,
  priceListsCreate,
  priceListsDelete,
  priceListsUpdate,
  usePriceListItemsList,
  usePriceListsList,
  usePriceListsRetrieve,
} from "@/lib/api/generated/endpoints/pricing/pricing";
import type { PriceList, PriceListItem, Warning } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { useDebounced } from "@/lib/use-debounced";

import { ProductPicker, type Picked } from "./pickers";

const clean = (v: string) => v.trim().replaceAll(",", "");

export function PriceListsPage() {
  const t = useTranslations("pricing.lists");
  const errors = useErrorText();
  const { can } = useAuth();
  const manage = can("pricing.manage");
  const cursor = useCursor();
  const query = usePriceListsList({ cursor: cursor.cursor });
  const page = query.data?.data;
  const refresh = () => void query.refetch();
  const fields = [
    { name: "name", label: t("name"), required: true },
    { name: "description", label: t("descriptionField") },
  ];
  const columns: DataTableColumn<PriceList>[] = [
    {
      id: "name",
      header: t("name"),
      cell: ({ row }) => (
        <Link
          href={`/manage/pricing/price-lists/${row.original.id}`}
          className="block font-medium hover:underline"
        >
          {row.original.name}
          {row.original.description ? (
            <span className="text-muted-foreground block text-xs font-normal">
              {row.original.description}
            </span>
          ) : null}
        </Link>
      ),
    },
    { id: "items", header: t("items"), cell: ({ row }) => row.original.item_count },
    { id: "shops", header: t("shops"), cell: ({ row }) => row.original.shop_count },
    {
      id: "actions",
      header: "",
      cell: ({ row }) =>
        manage ? (
          <span className="flex justify-end">
            <FieldsDialog
              trigger={
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-10"
                  aria-label={t("rename", { name: row.original.name })}
                >
                  <Pencil aria-hidden />
                </Button>
              }
              title={t("rename", { name: row.original.name })}
              fields={fields}
              initial={{ name: row.original.name, description: row.original.description ?? "" }}
              submitLabel={t("save")}
              onSubmit={async (v) => {
                await priceListsUpdate(row.original.id, {
                  name: String(v.name),
                  description: String(v.description),
                });
                refresh();
              }}
            />
            <ConfirmDialog
              destructive
              trigger={
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-10"
                  aria-label={t("delete", { name: row.original.name })}
                >
                  <Trash2 aria-hidden />
                </Button>
              }
              title={t("delete", { name: row.original.name })}
              description={t("deleteBody")}
              confirmLabel={t("deleteConfirm")}
              onConfirm={async () => {
                try {
                  await priceListsDelete(row.original.id);
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
              initial={{ name: "", description: "" }}
              submitLabel={t("add")}
              onSubmit={async (v) => {
                await priceListsCreate({
                  name: String(v.name),
                  description: String(v.description),
                });
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
        numericColumns={["items", "shops"]}
        pagination={cursor.pagination(page)}
        empty={{ title: t("emptyTitle"), description: t("emptyBody") }}
      />
    </>
  );
}

/** Inline editor for one list price; saves only when the value changed. */
function PriceCell({
  item,
  priceListId,
  disabled,
  onSaved,
}: {
  item: PriceListItem;
  priceListId: string;
  disabled: boolean;
  onSaved: (warnings: readonly Warning[]) => void;
}) {
  const t = useTranslations("pricing.items");
  const errors = useErrorText();
  const [value, setValue] = useState(item.price);
  const [error, setError] = useState<string | null>(null);
  const changed = clean(value) !== item.price;
  async function save() {
    setError(null);
    try {
      const response = await priceListItemsUpsert(priceListId, {
        items: [{ product: item.product.id, price: clean(value) }],
      });
      toast.success(t("saved"));
      onSaved(response.data.warnings);
    } catch (err) {
      const fields = errors.fields(err);
      setError(fields["items.0.price"] ?? errors.message(err));
    }
  }
  return (
    <form
      className="flex items-center justify-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (changed) void save();
      }}
    >
      <Input
        inputMode="decimal"
        value={value}
        disabled={disabled}
        onChange={(e) => setValue(e.target.value)}
        aria-label={t("priceFor", { name: item.product.name })}
        aria-invalid={Boolean(error)}
        title={error ?? undefined}
        className="h-10 w-28 text-right tabular-nums"
      />
      {changed ? (
        <Button type="submit" size="sm" className="min-h-9">
          {t("save")}
        </Button>
      ) : null}
      {error ? (
        <span role="alert" className="text-destructive text-xs">
          {error}
        </span>
      ) : null}
    </form>
  );
}

function AddItemDialog({
  priceListId,
  onAdded,
}: {
  priceListId: string;
  onAdded: (warnings: readonly Warning[]) => void;
}) {
  const t = useTranslations("pricing.items");
  const tc = useTranslations("common");
  const errors = useErrorText();
  const [open, setOpen] = useState(false);
  const [product, setProduct] = useState<Picked | null>(null);
  const [price, setPrice] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setProduct(null);
          setPrice("");
          setFieldErrors({});
        }
      }}
    >
      <DialogTrigger asChild>
        <Button className="min-h-10">
          <Plus aria-hidden />
          {t("add")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!product) {
              setFieldErrors({ product: t("chooseProduct") });
              return;
            }
            setBusy(true);
            setFieldErrors({});
            try {
              const response = await priceListItemsUpsert(priceListId, {
                items: [{ product: product.id, price: clean(price) }],
              });
              setOpen(false);
              onAdded(response.data.warnings);
            } catch (err) {
              const fields = errors.fields(err);
              setFieldErrors({
                product: fields["items.0.product"] ?? "",
                price:
                  fields["items.0.price"] ??
                  (Object.keys(fields).length ? "" : errors.message(err)),
              });
            } finally {
              setBusy(false);
            }
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("add")}</DialogTitle>
          </DialogHeader>
          <FormField label={t("product")} required error={fieldErrors.product || undefined}>
            <ProductPicker value={product} onChange={setProduct} />
          </FormField>
          <FormField label={t("price")} required error={fieldErrors.price || undefined}>
            <Input
              inputMode="decimal"
              className="h-10"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
            />
          </FormField>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              {tc("cancel")}
            </Button>
            <Button type="submit" disabled={busy || !price.trim()}>
              {t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function PriceListDetailPage({ priceListId }: { priceListId: string }) {
  const t = useTranslations("pricing.items");
  const errors = useErrorText();
  const router = useRouter();
  const { can } = useAuth();
  const manage = can("pricing.manage");
  const [search, setSearch] = useState("");
  const [warnings, setWarnings] = useState<readonly Warning[]>([]);
  const debounced = useDebounced(search.trim());
  const cursor = useCursor();
  const list = usePriceListsRetrieve(priceListId);
  const items = usePriceListItemsList(priceListId, {
    cursor: cursor.cursor,
    search: debounced || undefined,
  });
  if (list.isLoading) return <PageSkeleton />;
  if (list.error || !list.data) {
    return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  }
  const priceList = list.data.data;
  const page = items.data?.data;
  const refresh = (next: readonly Warning[] = []) => {
    setWarnings(next);
    void items.refetch();
    void list.refetch();
  };
  const columns: DataTableColumn<PriceListItem>[] = [
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <span>
          <span className="block font-medium">{row.original.product.name}</span>
          <span className="text-muted-foreground block text-xs">
            {row.original.product.code} · {row.original.unit}
          </span>
        </span>
      ),
    },
    {
      id: "base",
      header: t("standardPrice"),
      cell: ({ row }) => <MoneyText value={row.original.base_price} />,
    },
    {
      id: "price",
      header: t("price"),
      cell: ({ row }) => (
        <PriceCell
          key={row.original.updated_at}
          item={row.original}
          priceListId={priceListId}
          disabled={!manage}
          onSaved={refresh}
        />
      ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) =>
        manage ? (
          <ConfirmDialog
            destructive
            trigger={
              <Button
                variant="ghost"
                size="icon"
                className="size-10"
                aria-label={t("remove", { name: row.original.product.name })}
              >
                <Trash2 aria-hidden />
              </Button>
            }
            title={t("remove", { name: row.original.product.name })}
            description={t("removeBody")}
            confirmLabel={t("removeConfirm")}
            onConfirm={async () => {
              try {
                await priceListItemsDelete(priceListId, row.original.product.id);
                refresh();
              } catch (err) {
                toast.error(errors.message(err));
              }
            }}
          />
        ) : null,
    },
  ];
  return (
    <>
      <Button asChild variant="ghost" className="mb-2 -ml-3 min-h-10">
        <Link href="/manage/pricing/price-lists">
          <ArrowLeft aria-hidden />
          {t("back")}
        </Link>
      </Button>
      <PageHeader
        title={priceList.name}
        description={t("summary", { items: priceList.item_count, shops: priceList.shop_count })}
        actions={manage ? <AddItemDialog priceListId={priceListId} onAdded={refresh} /> : undefined}
      />
      <p className="text-muted-foreground mb-4 text-sm">{t("explain")}</p>
      <div className="mb-4">
        <WarningList warnings={warnings} keys={{ FREE_GOODS: "FREE_GOODS_PRICE_LIST" }} />
      </div>
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.product.id}
        isLoading={items.isLoading}
        error={items.error}
        onRetry={() => void items.refetch()}
        numericColumns={["base", "price"]}
        pagination={cursor.pagination(page)}
        empty={
          debounced
            ? { title: t("noMatchTitle") }
            : { title: t("emptyTitle"), description: t("emptyBody") }
        }
        toolbar={
          <Input
            type="search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              cursor.reset();
            }}
            placeholder={t("search")}
            aria-label={t("search")}
            className="h-10 w-full sm:w-64"
          />
        }
      />
      {priceList.shop_count === 0 && manage ? (
        <p className="text-muted-foreground mt-4 text-sm">
          {t("noShops")}{" "}
          <Button
            variant="link"
            className="h-auto p-0"
            onClick={() => router.push("/manage/retailers")}
          >
            {t("assignShops")}
          </Button>
        </p>
      ) : null}
    </>
  );
}
