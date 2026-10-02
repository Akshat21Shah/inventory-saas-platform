"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { lineKey, ProblemText } from "@/components/shop/cart";
import { FreeLineLabel, OfferHint } from "@/components/shop/free-goods";
import { StepperControl } from "@/components/shop/quantity-stepper";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useCatalogProductsList } from "@/lib/api/generated/endpoints/catalog/catalog";
import {
  getRetailerCartRetrieveQueryKey,
  ordersPlaceOnBehalf,
  retailerCartLineSet,
  useRetailerCartRetrieve,
} from "@/lib/api/generated/endpoints/orders/orders";
import {
  useRetailersList,
  useRetailersRetrieve,
} from "@/lib/api/generated/endpoints/retailers/retailers";
import type { Quote, RetailerList } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatMoney, formatQty } from "@/lib/format";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";
import { useDebounced } from "@/lib/use-debounced";

import { OrdersNav } from "./orders-nav";

function PickShop({ onPick }: { onPick: (shop: RetailerList) => void }) {
  const t = useTranslations("orders.onBehalf");
  const [text, setText] = useState("");
  const search = useDebounced(text.trim(), 250);
  const query = useRetailersList({ search: search || undefined, status: "ACTIVE", page_size: 20 });
  const shops = query.data?.data.results ?? [];
  return (
    <section className="space-y-3" aria-labelledby="shop-heading">
      <h2 id="shop-heading" className="text-lg font-semibold">
        {t("pickShop")}
      </h2>
      <div className="relative max-w-md">
        <Search
          aria-hidden
          className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2"
        />
        <Input
          type="search"
          value={text}
          autoFocus
          onChange={(e) => setText(e.target.value)}
          placeholder={t("shopSearch")}
          aria-label={t("shopSearch")}
          className="min-h-11 pl-9"
        />
      </div>
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : shops.length === 0 ? (
        <EmptyState title={t("noShops")} />
      ) : (
        <ul className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {shops.map((shop) => (
            <li key={shop.id}>
              <button
                type="button"
                onClick={() => onPick(shop)}
                className="hover:bg-muted/50 flex min-h-14 w-full flex-col items-start rounded-xl border p-3 text-left"
              >
                <span className="font-medium">{shop.shop_name}</span>
                <span className="text-muted-foreground text-xs">
                  {shop.code} · {shop.owner_name || shop.mobile}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function AddProducts({ shopId, cart }: { shopId: string; cart: Quote | undefined }) {
  const t = useTranslations("orders.onBehalf");
  const client = useQueryClient();
  const { message } = useErrorText();
  const [text, setText] = useState("");
  const search = useDebounced(text.trim(), 250);
  const [qty, setQty] = useState<Record<string, string>>({});
  const products = useCatalogProductsList(
    { search, page_size: 10 },
    { query: { enabled: search.length > 1 } },
  );
  const inCart = new Set(cart?.lines.filter((l) => !l.is_free).map((l) => l.product_id));
  const add = async (productId: string) => {
    try {
      const response = await retailerCartLineSet(shopId, productId, {
        quantity: qty[productId] || "1",
      });
      client.setQueryData(getRetailerCartRetrieveQueryKey(shopId), response);
      setQty((q) => ({ ...q, [productId]: "" }));
    } catch (error) {
      toast.error(message(error));
    }
  };
  return (
    <section className="space-y-3" aria-labelledby="products-heading">
      <h2 id="products-heading" className="font-semibold">
        {t("addProducts")}
      </h2>
      <Input
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t("productSearch")}
        aria-label={t("productSearch")}
        className="min-h-11"
      />
      <p className="text-muted-foreground text-xs">{t("pricesNote")}</p>
      <ul className="space-y-2">
        {(products.data?.data.results ?? []).map((product) => (
          <li key={product.id} className="flex flex-wrap items-center gap-2 rounded-xl border p-3">
            <span className="min-w-0 flex-1">
              <span className="block font-medium">{product.name}</span>
              <span className="text-muted-foreground text-xs">
                {product.code}
                {!product.show_in_shop || !product.is_active ? ` · ${t("notInShop")}` : ""}
              </span>
            </span>
            <Input
              inputMode="decimal"
              aria-label={t("qtyFor", { name: product.name })}
              className="min-h-10 w-20 text-right"
              placeholder="1"
              value={qty[product.id] ?? ""}
              onChange={(e) => setQty((q) => ({ ...q, [product.id]: e.target.value.trim() }))}
            />
            <Button
              className="min-h-10"
              variant={inCart.has(product.id) ? "outline" : "default"}
              onClick={() => void add(product.id)}
            >
              {inCart.has(product.id) ? t("update") : t("add")}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function StaffCart({ shopId }: { shopId: string }) {
  const t = useTranslations("orders.onBehalf");
  const cartT = useTranslations("shop.cart");
  const router = useRouter();
  const client = useQueryClient();
  const { message } = useErrorText();
  const [address, setAddress] = useState<string | undefined>(undefined);
  const [note, setNote] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const shop = useRetailersRetrieve(shopId);
  const query = useRetailerCartRetrieve(shopId, address ? { address } : undefined);
  const cart = query.data?.data;
  const addresses = shop.data?.data.addresses ?? [];

  const set = async (productId: string, quantity: string) => {
    try {
      const response = await retailerCartLineSet(shopId, productId, { quantity });
      client.setQueryData(getRetailerCartRetrieveQueryKey(shopId), response);
      void query.refetch();
      setKey(newIdempotencyKey()); // a changed cart is a new attempt
    } catch (error) {
      toast.error(message(error));
    }
  };

  const place = async () => {
    if (!cart) return;
    setBusy(true);
    try {
      const response = await ordersPlaceOnBehalf(
        {
          retailer: shopId,
          expected_total: cart.expected_total,
          address: cart.address_id ?? null,
          note: note.trim(),
        },
        idempotent(key),
      );
      toast.success(t("placed", { number: response.data.number }));
      router.push(`/manage/orders/${response.data.id}`);
    } catch (error) {
      toast.error(message(error));
      void query.refetch();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_24rem] xl:items-start">
      <AddProducts shopId={shopId} cart={cart} />
      <section className="space-y-4 rounded-xl border p-4" aria-labelledby="cart-heading">
        <h2 id="cart-heading" className="font-semibold">
          {t("cartTitle", { shop: shop.data?.data.shop_name ?? "" })}
        </h2>
        {query.isLoading ? (
          <CardSkeleton />
        ) : query.error ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : !cart || cart.lines.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("cartEmpty")}</p>
        ) : (
          <>
            <ul className="space-y-3">
              {cart.lines.map((line) => (
                <li key={lineKey(line)} className="space-y-1.5">
                  <div className="flex justify-between gap-2 text-sm">
                    <span className="font-medium">{line.product?.name ?? line.product_id}</span>
                    {line.is_free ? (
                      <span className="text-success-strong font-medium">
                        {t("freeQty", { qty: formatQty(line.quantity) })}
                      </span>
                    ) : line.line_total ? (
                      <MoneyText value={line.line_total} />
                    ) : null}
                  </div>
                  {line.is_free ? <FreeLineLabel scheme={line.scheme?.name ?? ""} /> : null}
                  {line.later_qty !== "0.000" ? (
                    <p className="text-info-strong text-xs">
                      {t("later", { qty: formatQty(line.later_qty) })}
                    </p>
                  ) : null}
                  {line.is_free ? null : <OfferHint offer={line.offer} />}
                  {line.product && !line.is_free ? (
                    <StepperControl
                      product={line.product}
                      qty={line.quantity}
                      onSet={(quantity) => void set(line.product_id, quantity)}
                    />
                  ) : null}
                  {line.problems.map((problem) => (
                    <p
                      key={problem.code}
                      className={
                        problem.blocking
                          ? "text-destructive text-xs"
                          : "text-warning-strong text-xs"
                      }
                    >
                      <ProblemText
                        problem={problem}
                        unit={line.product?.unit.name}
                        audience="staff"
                      />
                    </p>
                  ))}
                </li>
              ))}
            </ul>
            {addresses.length > 1 ? (
              <div className="space-y-1.5">
                <Label htmlFor="staff-address">{cartT("deliverTo")}</Label>
                <select
                  id="staff-address"
                  className="border-input bg-background h-10 w-full rounded-md border px-3"
                  value={cart.address_id ?? ""}
                  onChange={(e) => setAddress(e.target.value || undefined)}
                >
                  {addresses.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.label || a.line1}, {a.city}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className="space-y-1.5">
              <Label htmlFor="staff-note">{cartT("noteLabel")}</Label>
              <Textarea
                id="staff-note"
                value={note}
                maxLength={500}
                onChange={(e) => setNote(e.target.value)}
                className="min-h-16"
              />
            </div>
            <dl className="space-y-1 text-sm">
              <div className="flex justify-between">
                <dt>{cartT("gst")}</dt>
                <dd>
                  <MoneyText value={cart.totals.tax} />
                </dd>
              </div>
              <div className="flex justify-between text-base font-semibold">
                <dt>{cartT("total")}</dt>
                <dd>
                  <MoneyText value={cart.totals.grand_total} />
                </dd>
              </div>
            </dl>
            {cart.problems
              .filter((problem) => problem.code !== "CREDIT_APPROVAL_NEEDED")
              .map((problem) => (
                <p key={problem.code} className="bg-warning/15 rounded-lg p-2 text-sm">
                  <ProblemText problem={problem} audience="staff" />
                </p>
              ))}
            {cart.credit.outcome === "NEEDS_APPROVAL" ? (
              <p className="bg-info/10 rounded-lg p-2 text-sm">
                {t(cart.credit.reason === "OVERDUE" ? "needsApprovalOverdue" : "needsApproval")}
              </p>
            ) : null}
            <Button
              className="min-h-11 w-full"
              disabled={busy || !cart.can_place}
              onClick={() => void place()}
            >
              {t("place", { total: formatMoney(cart.totals.grand_total) })}
            </Button>
          </>
        )}
      </section>
    </div>
  );
}

/** A salesman (or other staff with orders.create_on_behalf) orders for a shop from a separate
 * cart of their own (ADR-044); the order says "Placed by Priya (Sales)". */
type PickedShop = Pick<RetailerList, "id" | "shop_name" | "status">;

export function OrderOnBehalfPage() {
  const t = useTranslations("orders.onBehalf");
  // ``?shop=`` opens the shop straight away (e.g. "Place an order" on the shop activity list).
  const presetId = useSearchParams().get("shop");
  const [picked, setPicked] = useState<PickedShop | null>(null);
  const [usePreset, setUsePreset] = useState(Boolean(presetId));
  const preset = useRetailersRetrieve(presetId ?? "", {
    query: { enabled: usePreset && Boolean(presetId) },
  });
  const shop: PickedShop | null = picked ?? (usePreset && preset.data ? preset.data.data : null);
  const setShop = (next: PickedShop | null) => {
    setPicked(next);
    setUsePreset(false);
  };
  if (usePreset && presetId && preset.isLoading) return <CardSkeleton />;
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <OrdersNav />
      {shop ? (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="ghost" className="-ml-3 min-h-10" onClick={() => setShop(null)}>
              <ArrowLeft aria-hidden />
              {t("changeShop")}
            </Button>
            <span className="font-semibold">{shop.shop_name}</span>
            {shop.status !== "ACTIVE" ? <StatusBadge status={shop.status} /> : null}
            <Link
              href={`/manage/retailers/${shop.id}`}
              className="text-brand-700 text-sm hover:underline"
            >
              {t("shopDetails")}
            </Link>
          </div>
          <StaffCart shopId={shop.id} />
        </div>
      ) : (
        <PickShop onPick={setShop} />
      )}
    </>
  );
}
