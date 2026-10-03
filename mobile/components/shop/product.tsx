/**
 * A product as the shop sees it, the app's twin of the web's catalogue pieces: prices exactly as
 * the server worked them out (nothing is calculated here), availability in words, the ordering
 * rules and the stepper, so a product can be added without opening it.
 */
import Feather from "@expo/vector-icons/Feather";
import { Image } from "expo-image";
import { Link } from "expo-router";
import { Pressable, StyleSheet, View } from "react-native";

import { MoneyText } from "@/components/shared/values";
import { StatusBadge } from "@/components/shared/status-badge";
import { Card } from "@/components/ui/card";
import { Text } from "@/components/ui/text";
import type { SchemeTerms, ShopPrice, ShopProduct } from "@/lib/api/generated/model";
import { useAuth } from "@/lib/auth/auth-provider";
import { useTranslations } from "@/lib/i18n/translations";
import { formatQty } from "@/lib/shared/format";
import { space, useTheme } from "@/lib/theme/theme";

import { QuantityStepper } from "./quantity-stepper";

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
    <View style={styles.price}>
      <View style={styles.inline}>
        <MoneyText value={price.net_unit_price} weight="semibold" size={large ? "2xl" : "lg"} />
        {discounted ? (
          <MoneyText value={price.unit_price} tone="muted" size="sm" style={styles.strike} />
        ) : null}
        <Text tone="muted" size="xs">
          {price.prices_include_gst
            ? t("inclGst")
            : t("plusGst", { rate: formatQty(price.gst_rate) })}
        </Text>
      </View>
      {discounted ? (
        <Text tone="success" size="sm" weight="medium">
          {t("youSave")}{" "}
          <MoneyText value={price.discount_per_unit} tone="success" size="sm" weight="medium" />{" "}
          {t("eachPercent", { percent: formatQty(price.discount_percent, 2) })}
        </Text>
      ) : null}
      {mrp ? (
        <Text tone="muted" size="xs">
          {t("mrp")} <MoneyText value={mrp} tone="muted" size="xs" />
        </Text>
      ) : null}
    </View>
  );
}

/** "In stock", "Low stock", "Available on backorder" or "Out of stock" (the server's words). */
export function Availability({ product }: { product: Pick<ShopProduct, "availability" | "unit"> }) {
  const t = useTranslations("shop.stock");
  const { status, quantity } = product.availability;
  return (
    <View style={styles.inline}>
      <StatusBadge status={status} />
      {quantity !== null && !/^0(\.0+)?$/.test(quantity) ? (
        <Text tone="muted" size="xs">
          {t("left", { qty: formatQty(quantity), unit: product.unit.name })}
        </Text>
      ) : null}
    </View>
  );
}

export function OwnBrandBadge() {
  const t = useTranslations("shop");
  const { colors } = useTheme();
  return (
    <View style={[styles.pill, { backgroundColor: colors.brand50 }]}>
      <Text size="xs" weight="medium" style={{ color: colors.brand800 }}>
        {t("ownBrand")}
      </Text>
    </View>
  );
}

export function Thumb({ url, size }: { url: string | null; size: number }) {
  const { colors, radius } = useTheme();
  if (!url) {
    return (
      <View
        style={[
          styles.thumb,
          { width: size, height: size, backgroundColor: colors.muted, borderRadius: radius },
        ]}
      >
        <Feather name="image" size={24} color={colors.mutedForeground} />
      </View>
    );
  }
  return (
    <Image
      source={url}
      contentFit="contain"
      cachePolicy="disk"
      recyclingKey={url}
      accessibilityIgnoresInvertColors
      style={{ width: size, height: size, borderRadius: radius, backgroundColor: colors.muted }}
    />
  );
}

export function OrderingNote({
  product,
}: {
  product: Pick<ShopProduct, "min_order_qty" | "order_multiple" | "unit">;
}) {
  const t = useTranslations("shop.product");
  const min = formatQty(product.min_order_qty);
  const step = formatQty(product.order_multiple);
  if (min === "1" && step === "1") return null;
  return (
    <Text tone="muted" size="xs">
      {t("minimum", { qty: min, unit: product.unit.name })}
      {step !== "1" ? ` · ${t("inSteps", { qty: step })}` : ""}
    </Text>
  );
}

/** "Buy 10, get 1 free": the server's scheme in plain words (ADR-056). */
export function useOfferText() {
  const t = useTranslations("shop.free");
  return (
    offer: Pick<SchemeTerms, "buy_qty" | "free_qty" | "same_product" | "free_product_name">,
  ) =>
    t("offer", {
      same: String(offer.same_product),
      buy: formatQty(offer.buy_qty),
      free: formatQty(offer.free_qty),
      product: offer.free_product_name,
    });
}

export function FreeOfferBadge({ offer }: { offer: SchemeTerms }) {
  const text = useOfferText();
  const { colors } = useTheme();
  return (
    <View style={[styles.pill, styles.inline, { backgroundColor: colors.success + "1f" }]}>
      <Feather name="gift" size={12} color={colors.successStrong} />
      <Text size="xs" weight="medium" tone="success">
        {text(offer)}
      </Text>
    </View>
  );
}

/** Out of stock can't be ordered now (with backorders on, the server says "Available on backorder"). */
export function orderable(product: Pick<ShopProduct, "availability">): boolean {
  return product.availability.status !== "OUT_OF_STOCK";
}

export function ProductCard({
  product,
  lastQuantity,
}: {
  product: ShopProduct;
  lastQuantity?: string;
}) {
  const t = useTranslations("shop.order");
  return (
    <Card>
      <Link href={`/shop/products/${product.id}`} asChild>
        <Pressable accessibilityRole="link" style={styles.cardTop}>
          <Thumb url={product.thumbnail_url} size={80} />
          <View style={styles.cardBody}>
            <Text weight="medium">{product.name}</Text>
            {product.brand ? (
              <View style={styles.inline}>
                <Text tone="muted" size="xs">
                  {product.brand.name}
                </Text>
                {product.own_brand ? <OwnBrandBadge /> : null}
              </View>
            ) : null}
            <PriceBlock price={product.price} mrp={product.mrp} />
            {product.free_offer ? <FreeOfferBadge offer={product.free_offer} /> : null}
            <Availability product={product} />
            <OrderingNote product={product} />
          </View>
        </Pressable>
      </Link>
      <View style={styles.cardFoot}>
        <Text tone="muted" size="xs" style={styles.flex}>
          {lastQuantity
            ? t("lastTime", { qty: formatQty(lastQuantity), unit: product.unit.name })
            : ""}
        </Text>
        <QuantityStepper product={product} disabled={!orderable(product)} />
      </View>
    </Card>
  );
}

export function OnHoldNotice() {
  const t = useTranslations("shop");
  const { me } = useAuth();
  const { colors, radius } = useTheme();
  if (!me?.retailer?.on_hold) return null;
  return (
    <View
      accessibilityRole="alert"
      style={[styles.notice, { backgroundColor: colors.warning + "26", borderRadius: radius }]}
    >
      <Feather name="alert-triangle" size={16} color={colors.warningStrong} />
      <Text size="sm" style={styles.flex}>
        {t("onHold")}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  price: { gap: 2 },
  inline: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space[2] },
  strike: { textDecorationLine: "line-through" },
  pill: {
    alignSelf: "flex-start",
    paddingHorizontal: space[2],
    paddingVertical: 2,
    borderRadius: 999,
  },
  thumb: { alignItems: "center", justifyContent: "center" },
  cardTop: { flexDirection: "row", gap: space[3] },
  cardBody: { flex: 1, gap: space[1] },
  cardFoot: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: space[3],
  },
  flex: { flex: 1 },
  notice: { flexDirection: "row", gap: space[2], padding: space[3], alignItems: "flex-start" },
});
