"use client";

import { Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { WarningList } from "@/components/catalog/product-editor";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { FormField } from "@/components/shared/form-field";
import { MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
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
  retailerPricesCreate,
  retailerPricesDelete,
  retailerPricesUpdate,
  useRetailerPricesList,
} from "@/lib/api/generated/endpoints/pricing/pricing";
import { useRetailersRetrieve } from "@/lib/api/generated/endpoints/retailers/retailers";
import type { RetailerPrice, Warning } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";

import { ProductPicker, RetailerPicker, type Picked } from "./pickers";

const clean = (v: string) => v.trim().replaceAll(",", "");
/** A special price words the free-goods warning for one shop and one product. */
export const SPECIAL_WARNING_KEYS = { FREE_GOODS: "FREE_GOODS_SPECIAL" };

function SpecialPriceDialog({
  row,
  retailer,
  onSaved,
}: {
  row?: RetailerPrice;
  retailer?: Picked | null;
  onSaved: (warnings: readonly Warning[]) => void;
}) {
  const t = useTranslations("pricing.special");
  const tc = useTranslations("common");
  const errors = useErrorText();
  const [open, setOpen] = useState(false);
  const [shop, setShop] = useState<Picked | null>(null);
  const [product, setProduct] = useState<Picked | null>(null);
  const [price, setPrice] = useState("");
  const [note, setNote] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const editing = Boolean(row);

  async function submit() {
    setFieldErrors({});
    if (!editing && (!shop || !product)) {
      setFieldErrors({
        ...(shop ? {} : { retailer: t("chooseShop") }),
        ...(product ? {} : { product: t("chooseProduct") }),
      });
      return;
    }
    setBusy(true);
    try {
      const response = row
        ? await retailerPricesUpdate(row.id, { price: clean(price), note })
        : await retailerPricesCreate({
            retailer: shop!.id,
            product: product!.id,
            price: clean(price),
            note,
          });
      toast.success(t("saved"));
      setOpen(false);
      onSaved(response.data.warnings);
    } catch (err) {
      const fields = errors.fields(err);
      setFieldErrors(Object.keys(fields).length ? fields : { price: errors.message(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setShop(retailer ?? null);
          setProduct(null);
          setPrice(row?.price ?? "");
          setNote(row?.note ?? "");
          setFieldErrors({});
        }
      }}
    >
      <DialogTrigger asChild>
        {row ? (
          <Button
            variant="ghost"
            size="icon"
            className="size-10"
            aria-label={t("edit", { product: row.product.name, shop: row.retailer.shop_name })}
          >
            <Pencil aria-hidden />
          </Button>
        ) : (
          <Button className="min-h-10">
            <Plus aria-hidden />
            {t("add")}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <DialogHeader>
            <DialogTitle>
              {row
                ? t("edit", { product: row.product.name, shop: row.retailer.shop_name })
                : t("add")}
            </DialogTitle>
          </DialogHeader>
          {row ? (
            <p className="text-muted-foreground text-sm">
              {t("standardIs")} <MoneyText value={row.base_price} />
            </p>
          ) : (
            <>
              <FormField label={t("shop")} required error={fieldErrors.retailer}>
                <RetailerPicker value={shop} onChange={setShop} />
              </FormField>
              <FormField label={t("product")} required error={fieldErrors.product}>
                <ProductPicker value={product} onChange={setProduct} />
              </FormField>
            </>
          )}
          <FormField label={t("price")} required error={fieldErrors.price} hint={t("priceHint")}>
            <Input
              inputMode="decimal"
              className="h-10"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
            />
          </FormField>
          <FormField label={t("note")} error={fieldErrors.note} hint={t("noteHint")}>
            <Input className="h-10" value={note} onChange={(e) => setNote(e.target.value)} />
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

export function SpecialPricesPage() {
  const t = useTranslations("pricing.special");
  const errors = useErrorText();
  const params = useSearchParams();
  const retailerId = params.get("retailer") ?? undefined;
  const { can } = useAuth();
  const manage = can("pricing.manage");
  const cursor = useCursor();
  const [warnings, setWarnings] = useState<readonly Warning[]>([]);
  const query = useRetailerPricesList({ cursor: cursor.cursor, retailer: retailerId });
  const shop = useRetailersRetrieve(retailerId ?? "", { query: { enabled: Boolean(retailerId) } });
  const shopData = shop.data?.data;
  const page = query.data?.data;
  const saved = (next: readonly Warning[]) => {
    setWarnings(next);
    void query.refetch();
  };
  const columns: DataTableColumn<RetailerPrice>[] = [
    ...(retailerId
      ? []
      : [
          {
            id: "shop",
            header: t("shop"),
            cell: ({ row }) => (
              <Link
                href={`/manage/retailers/${row.original.retailer.id}`}
                className="hover:underline"
              >
                {row.original.retailer.shop_name}
                <span className="text-muted-foreground block text-xs">
                  {row.original.retailer.code}
                </span>
              </Link>
            ),
          } satisfies DataTableColumn<RetailerPrice>,
        ]),
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <span>
          {row.original.product.name}
          <span className="text-muted-foreground block text-xs">{row.original.product.code}</span>
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
      cell: ({ row }) => <MoneyText value={row.original.price} className="font-medium" />,
    },
    { id: "note", header: t("note"), cell: ({ row }) => row.original.note || "—" },
    {
      id: "actions",
      header: "",
      cell: ({ row }) =>
        manage ? (
          <span className="flex justify-end">
            <SpecialPriceDialog row={row.original} onSaved={saved} />
            <ConfirmDialog
              destructive
              trigger={
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-10"
                  aria-label={t("remove", { product: row.original.product.name })}
                >
                  <Trash2 aria-hidden />
                </Button>
              }
              title={t("remove", { product: row.original.product.name })}
              description={t("removeBody")}
              confirmLabel={t("removeConfirm")}
              onConfirm={async () => {
                try {
                  await retailerPricesDelete(row.original.id);
                  void query.refetch();
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
        title={shopData ? t("titleFor", { shop: shopData.shop_name }) : t("title")}
        description={t("description")}
        actions={
          manage ? (
            <SpecialPriceDialog
              retailer={shopData ? { id: shopData.id, label: shopData.shop_name } : null}
              onSaved={saved}
            />
          ) : undefined
        }
      />
      {retailerId ? (
        <Button asChild variant="link" className="mb-3 h-auto p-0">
          <Link href="/manage/pricing/special-prices">{t("allShops")}</Link>
        </Button>
      ) : null}
      <div className="mb-4">
        <WarningList warnings={warnings} keys={SPECIAL_WARNING_KEYS} />
      </div>
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["base", "price"]}
        pagination={cursor.pagination(page)}
        empty={{ title: t("emptyTitle"), description: t("emptyBody") }}
      />
    </>
  );
}
