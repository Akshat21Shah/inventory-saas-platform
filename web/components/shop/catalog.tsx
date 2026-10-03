"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronRight, ImageOff, Search, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { MoneyText } from "@/components/shared/money-text";
import { CardSkeleton, PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  shopProducts,
  useShopBrands,
  useShopCategories,
  useShopProduct,
} from "@/lib/api/generated/endpoints/shop/shop";
import type {
  ShopCategory,
  ShopPrice,
  ShopProduct,
  ShopProductsParams,
} from "@/lib/api/generated/model";
import { formatQty } from "@/lib/format";
import { useTranslations } from "@/lib/i18n/translations";
import { isZero } from "@/lib/qty";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";

import { FreeOfferBadge, FreeOfferDetails } from "./free-goods";
import { useCart } from "./cart-state";
import { QuantityStepper } from "./quantity-stepper";

/** Children arrive as plain objects with the same shape. */
const childrenOf = (c: ShopCategory) => c.children as unknown as ShopCategory[];

interface Found {
  node: ShopCategory;
  trail: ShopCategory[];
}

function findCategory(nodes: ShopCategory[], id: string, trail: ShopCategory[] = []): Found | null {
  for (const node of nodes) {
    if (node.id === id) return { node, trail };
    const found = findCategory(childrenOf(node), id, [...trail, node]);
    if (found) return found;
  }
  return null;
}

function cursorOf(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  return new URL(url, "http://localhost").searchParams.get("cursor") ?? undefined;
}

export function OnHoldNotice() {
  const t = useTranslations("shop");
  const { me } = useAuth();
  if (!me?.retailer?.on_hold) return null;
  return (
    <p role="status" className="bg-warning/15 mb-4 flex gap-2 rounded-xl p-3 text-sm">
      <TriangleAlert aria-hidden className="text-warning-strong mt-0.5 size-4 shrink-0" />
      {t("onHold")}
    </p>
  );
}

/** Prices exactly as the server worked them out; nothing is calculated here. */
export function PriceBlock({
  price,
  mrp,
  large,
}: {
  price: ShopPrice;
  mrp: string | null;
  large?: boolean;
}) {
  const t = useTranslations("shop.price");
  const discounted = price.discount_total !== "0.00";
  return (
    <div className="space-y-0.5">
      <p className="flex flex-wrap items-baseline gap-x-2">
        <MoneyText
          value={price.net_unit_price}
          className={cn("font-semibold", large ? "text-2xl" : "text-lg")}
        />
        {discounted ? (
          <MoneyText
            value={price.unit_price}
            className="text-muted-foreground text-sm line-through"
          />
        ) : null}
        <span className="text-muted-foreground text-xs">
          {price.prices_include_gst
            ? t("inclGst")
            : t("plusGst", { rate: formatQty(price.gst_rate) })}
        </span>
      </p>
      {price.discount_total !== "0.00" ? (
        <p className="text-success-strong text-sm font-medium">
          {t("youSave")} <MoneyText value={price.discount_per_unit} />{" "}
          {t("eachPercent", { percent: formatQty(price.discount_percent, 2) })}
        </p>
      ) : null}
      {mrp ? (
        <p className="text-muted-foreground text-xs">
          {t("mrp")} <MoneyText value={mrp} />
        </p>
      ) : null}
    </div>
  );
}

/** "In stock", "Low stock", "Available on backorder" or "Out of stock"; the quantity only when
 * the distributor shows exact stock (ADR-041 item 12). Never computed here. */
function Availability({ product }: { product: Pick<ShopProduct, "availability" | "unit"> }) {
  const t = useTranslations("shop.stock");
  const { status, quantity } = product.availability;
  return (
    <span className="flex flex-wrap items-center gap-2">
      <StatusBadge status={status} />
      {quantity !== null && Number(quantity) > 0 ? (
        <span className="text-muted-foreground text-xs">
          {t("left", { qty: formatQty(quantity), unit: product.unit.name })}
        </span>
      ) : null}
    </span>
  );
}

function OwnBrandBadge() {
  const t = useTranslations("shop");
  return (
    <span className="bg-brand-50 text-brand-800 rounded-full px-2 py-0.5 text-xs font-medium">
      {t("ownBrand")}
    </span>
  );
}

function Thumb({ url, className }: { url: string | null; className?: string }) {
  return url ? (
    // eslint-disable-next-line @next/next/no-img-element -- long-cached public CDN image
    <img src={url} alt="" loading="lazy" className={cn("bg-muted object-contain", className)} />
  ) : (
    <span
      className={cn("bg-muted text-muted-foreground flex items-center justify-center", className)}
    >
      <ImageOff aria-hidden className="size-6" />
    </span>
  );
}

function OrderingNote({
  product,
}: {
  product: Pick<ShopProduct, "min_order_qty" | "order_multiple" | "unit">;
}) {
  const t = useTranslations("shop.product");
  const min = formatQty(product.min_order_qty);
  const step = formatQty(product.order_multiple);
  if (min === "1" && step === "1") return null;
  return (
    <p className="text-muted-foreground text-xs">
      {t("minimum", { qty: min, unit: product.unit.name })}
      {step !== "1" ? ` · ${t("inSteps", { qty: step })}` : ""}
    </p>
  );
}

/** "Out of stock" means it can't be ordered now (with backorders on, the server says "Available
 * on backorder" instead); the label comes from the server. */
function orderable(product: Pick<ShopProduct, "availability">): boolean {
  return product.availability.status !== "OUT_OF_STOCK";
}

/** A product with its price, stock and the order stepper, so it can be added without opening it
 * (search, categories and "Repeat last order", ADR-044). */
export function ProductCard({
  product,
  lastQuantity,
}: {
  product: ShopProduct;
  /** "Repeat last order": what the shop ordered last time. */
  lastQuantity?: string;
}) {
  const t = useTranslations("shop.order");
  return (
    <li className="flex flex-col gap-3 rounded-xl border p-3">
      <Link
        href={`/shop/products/${product.id}`}
        className="hover:bg-muted/50 -m-1 flex min-h-20 gap-3 rounded-lg p-1"
      >
        <Thumb url={product.thumbnail_url} className="size-20 shrink-0 rounded-lg" />
        <span className="min-w-0 flex-1 space-y-1">
          <span className="block leading-snug font-medium">{product.name}</span>
          {product.brand ? (
            <span className="text-muted-foreground flex items-center gap-2 text-xs">
              {product.brand.name}
              {product.own_brand ? <OwnBrandBadge /> : null}
            </span>
          ) : null}
          <PriceBlock price={product.price} mrp={product.mrp} />
          {product.free_offer ? <FreeOfferBadge offer={product.free_offer} /> : null}
          <Availability product={product} />
          <OrderingNote product={product} />
        </span>
      </Link>
      <div className="flex items-center justify-between gap-3">
        <span className="text-muted-foreground min-w-0 text-xs">
          {lastQuantity
            ? t("lastTime", { qty: formatQty(lastQuantity), unit: product.unit.name })
            : null}
        </span>
        <QuantityStepper product={product} disabled={!orderable(product)} className="shrink-0" />
      </div>
    </li>
  );
}

/** Products from the server, 30 at a time, with "show more". */
function ProductList({ params }: { params: ShopProductsParams }) {
  const t = useTranslations("shop");
  const query = useInfiniteQuery({
    queryKey: ["/api/v1/shop/products/", "infinite", params],
    queryFn: ({ pageParam }) => shopProducts({ ...params, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => cursorOf(last.data.next),
  });
  if (query.isLoading) {
    return (
      <div className="space-y-3">
        <CardSkeleton />
        <CardSkeleton />
      </div>
    );
  }
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const products = query.data?.pages.flatMap((p) => p.data.results) ?? [];
  if (products.length === 0) {
    return (
      <EmptyState
        title={params.search ? t("noMatchTitle") : t("noProductsTitle")}
        description={params.search ? t("noMatchBody") : t("noProductsBody")}
      />
    );
  }
  return (
    <div className="space-y-4">
      <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {products.map((product) => (
          <ProductCard key={product.id} product={product} />
        ))}
      </ul>
      {query.hasNextPage ? (
        <Button
          variant="outline"
          className="min-h-11 w-full"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {t("showMore")}
        </Button>
      ) : null}
    </div>
  );
}

export function SearchBox({ initial = "" }: { initial?: string }) {
  const t = useTranslations("shop");
  const router = useRouter();
  const [text, setText] = useState(initial);
  return (
    <form
      role="search"
      className="relative"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        router.push(`/shop/search?q=${encodeURIComponent(text.trim())}`);
      }}
    >
      <Search
        aria-hidden
        className="text-muted-foreground absolute top-1/2 left-3 size-5 -translate-y-1/2"
      />
      <Input
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t("searchPlaceholder")}
        aria-label={t("search")}
        className="h-12 pl-10 text-base"
      />
    </form>
  );
}

export function CategoryTiles({ categories }: { categories: ShopCategory[] }) {
  const t = useTranslations("shop");
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {categories.map((c) => (
        <li key={c.id}>
          <Link
            href={`/shop/catalog/${c.id}`}
            className="hover:bg-muted/50 flex min-h-16 items-center justify-between gap-2 rounded-xl border p-3"
          >
            <span className="min-w-0">
              <span className="block font-medium">{c.name}</span>
              <span className="text-muted-foreground block text-xs">
                {t("productCount", { count: c.product_count })}
              </span>
            </span>
            <ChevronRight aria-hidden className="text-muted-foreground size-4 shrink-0" />
          </Link>
        </li>
      ))}
    </ul>
  );
}

function BrandFilter({
  categoryId,
  value,
  onChange,
}: {
  categoryId?: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useTranslations("shop");
  const brands = useShopBrands({ category: categoryId }).data?.data ?? [];
  if (brands.length < 2) return null;
  return (
    <div className="-mx-4 overflow-x-auto px-4" role="group" aria-label={t("brandFilter")}>
      <div className="flex gap-2">
        {[{ id: "", name: t("allBrands") }, ...brands].map((b) => (
          <Button
            key={b.id || "all"}
            size="sm"
            variant={value === b.id ? "default" : "outline"}
            aria-pressed={value === b.id}
            className="min-h-10 shrink-0 rounded-full"
            onClick={() => onChange(b.id)}
          >
            {b.name}
          </Button>
        ))}
      </div>
    </div>
  );
}

export function CatalogPage({ categoryId }: { categoryId?: string }) {
  const t = useTranslations("shop");
  const categories = useShopCategories();
  const [brand, setBrand] = useState("");
  if (categories.isLoading) return <PageSkeleton />;
  const tree = categories.data?.data ?? [];
  const found = categoryId ? findCategory(tree, categoryId) : null;
  if (categoryId && !categories.error && !found) {
    return (
      <EmptyState
        title={t("categoryGoneTitle")}
        description={t("categoryGoneBody")}
        action={
          <Button asChild className="min-h-11">
            <Link href="/shop/catalog">{t("allProducts")}</Link>
          </Button>
        }
      />
    );
  }
  const children = found ? childrenOf(found.node) : tree;
  const parent = found?.trail.at(-1);
  return (
    <div className="space-y-5">
      {found ? (
        <Button asChild variant="ghost" className="-ml-3 min-h-11">
          <Link href={parent ? `/shop/catalog/${parent.id}` : "/shop/catalog"}>
            <ArrowLeft aria-hidden />
            {parent ? parent.name : t("allCategories")}
          </Link>
        </Button>
      ) : null}
      <h1 className="text-2xl font-semibold">{found ? found.node.name : t("catalogTitle")}</h1>
      <OnHoldNotice />
      <SearchBox />
      {children.length ? <CategoryTiles categories={children} /> : null}
      <BrandFilter categoryId={categoryId} value={brand} onChange={setBrand} />
      <ProductList params={{ category: categoryId, brand: brand || undefined }} />
    </div>
  );
}

export function SearchPage() {
  const t = useTranslations("shop");
  const params = useSearchParams();
  const initial = params.get("q") ?? "";
  const [text, setText] = useState(initial);
  const search = useDebounced(text.trim(), 250);
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("searchTitle")}</h1>
      <div role="search" className="relative">
        <Search
          aria-hidden
          className="text-muted-foreground absolute top-1/2 left-3 size-5 -translate-y-1/2"
        />
        <Input
          type="search"
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t("searchPlaceholder")}
          aria-label={t("search")}
          className="h-12 pl-10 text-base"
        />
      </div>
      {search ? (
        <ProductList params={{ search }} />
      ) : (
        <p className="text-muted-foreground text-sm">{t("searchHint")}</p>
      )}
    </div>
  );
}

function ProductOrderBox({ product }: { product: ShopProduct }) {
  const t = useTranslations("shop.order");
  const { quantityOf } = useCart();
  const inCart = !isZero(quantityOf(product.id));
  return (
    <section className="space-y-3 rounded-xl border p-4" aria-label={t("orderBox")}>
      <QuantityStepper product={product} disabled={!orderable(product)} wide />
      {!orderable(product) ? (
        <p className="text-muted-foreground text-sm">{t("cantOrder")}</p>
      ) : inCart ? (
        <Button asChild variant="outline" className="min-h-11 w-full">
          <Link href="/shop/cart">{t("goToCart")}</Link>
        </Button>
      ) : null}
    </section>
  );
}

export function ProductPage({ productId }: { productId: string }) {
  const t = useTranslations("shop.product");
  const ts = useTranslations("shop");
  const router = useRouter();
  const query = useShopProduct(productId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return (
      <EmptyState
        title={t("goneTitle")}
        description={t("goneBody")}
        action={
          <Button asChild className="min-h-11">
            <Link href="/shop/catalog">{ts("allProducts")}</Link>
          </Button>
        }
      />
    );
  }
  const product = query.data.data;
  return (
    <div className="space-y-5">
      <Button variant="ghost" className="-ml-3 min-h-11" onClick={() => router.back()}>
        <ArrowLeft aria-hidden />
        {t("back")}
      </Button>
      <OnHoldNotice />
      <div className="grid gap-6 lg:grid-cols-2 lg:items-start lg:gap-10">
        {product.images.length ? (
          <ul
            className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4"
            aria-label={t("photos")}
          >
            {product.images.map((image) => (
              <li key={image.id} className="w-4/5 shrink-0 snap-center sm:w-80 lg:w-full">
                {/* eslint-disable-next-line @next/next/no-img-element -- long-cached public CDN image */}
                <img
                  src={image.urls.medium}
                  alt={image.alt_text || product.name}
                  className="bg-muted aspect-square w-full rounded-xl object-contain"
                />
              </li>
            ))}
          </ul>
        ) : (
          <Thumb url={null} className="aspect-square w-full max-w-80 rounded-xl lg:max-w-none" />
        )}
        <div className="space-y-5">
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold">{product.name}</h1>
            {product.brand ? (
              <p className="text-muted-foreground flex items-center gap-2 text-sm">
                {product.brand.name}
                {product.own_brand ? <OwnBrandBadge /> : null}
              </p>
            ) : null}
          </div>
          <PriceBlock price={product.price} mrp={product.mrp} large />
          <Availability product={product} />
          <OrderingNote product={product} />
          {product.pack_unit && product.pack_size ? (
            <p className="text-sm">
              {t("pack", {
                pack: product.pack_unit.name,
                qty: formatQty(product.pack_size),
                unit: product.unit.name,
              })}
            </p>
          ) : null}
          {product.free_offer ? <FreeOfferDetails offer={product.free_offer} /> : null}
          {product.slab_hints.length ? (
            <section className="bg-success/10 space-y-1 rounded-xl p-4">
              <h2 className="font-semibold">{t("buyMore")}</h2>
              <ul className="space-y-1 text-sm">
                {product.slab_hints.map((hint) => (
                  <li key={hint.min_qty}>
                    {t("slab", { qty: formatQty(hint.min_qty) })}{" "}
                    <MoneyText value={hint.net_unit_price} className="font-semibold" />{" "}
                    {ts("price.each")}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {product.description ? (
            <p className="text-sm whitespace-pre-line">{product.description}</p>
          ) : null}
          <ProductOrderBox product={product} />
        </div>
      </div>
    </div>
  );
}
