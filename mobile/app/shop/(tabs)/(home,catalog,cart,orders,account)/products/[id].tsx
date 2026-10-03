import Feather from "@expo/vector-icons/Feather";
import { Image } from "expo-image";
import { router, useLocalSearchParams } from "expo-router";
import { ScrollView, StyleSheet, useWindowDimensions, View } from "react-native";

import { EmptyState, ListSkeleton } from "@/components/shared/states";
import { MoneyText } from "@/components/shared/values";
import {
  Availability,
  orderable,
  OnHoldNotice,
  OrderingNote,
  OwnBrandBadge,
  PriceBlock,
  Thumb,
  useOfferText,
} from "@/components/shop/product";
import { QuantityStepper } from "@/components/shop/quantity-stepper";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useShopProduct } from "@/lib/api/generated/endpoints/shop/shop";
import type { SchemeTerms } from "@/lib/api/generated/model";
import { useCart } from "@/lib/cart/cart-state";
import { useTranslations } from "@/lib/i18n/translations";
import { formatQty } from "@/lib/shared/format";
import { isZero } from "@/lib/shared/qty";
import { space, useTheme } from "@/lib/theme/theme";

function FreeOfferDetails({ offer }: { offer: SchemeTerms }) {
  const t = useTranslations("shop.free");
  const text = useOfferText();
  const { colors, radius } = useTheme();
  return (
    <View style={[styles.box, { backgroundColor: colors.success + "1a", borderRadius: radius }]}>
      <View style={styles.inline}>
        <Feather name="gift" size={16} color={colors.successStrong} />
        <Text weight="semibold">{text(offer)}</Text>
      </View>
      <Text size="sm">
        {offer.repeat ? t("every", { buy: formatQty(offer.buy_qty) }) : t("once")}
        {offer.max_free_qty ? ` ${t("cap", { max: formatQty(offer.max_free_qty) })}` : ""}
      </Text>
    </View>
  );
}

export default function ProductScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const t = useTranslations("shop.product");
  const ts = useTranslations("shop");
  const to = useTranslations("shop.order");
  const { width } = useWindowDimensions();
  const { colors, radius } = useTheme();
  const { quantityOf } = useCart();
  const query = useShopProduct(id);
  const product = query.data?.data;
  const photo = Math.min(width - space[8], 560);
  return (
    <>
      {query.isLoading ? (
        <Screen>
          <ListSkeleton rows={3} />
        </Screen>
      ) : !product ? (
        <Screen>
          <EmptyState
            icon="package"
            title={t("goneTitle")}
            body={t("goneBody")}
            action={{ label: ts("allProducts"), onPress: () => router.replace("/shop/catalog") }}
          />
        </Screen>
      ) : (
        <Screen refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
          <OnHoldNotice />
          {product.images.length ? (
            <ScrollView
              horizontal
              pagingEnabled
              showsHorizontalScrollIndicator={false}
              accessibilityLabel={t("photos")}
            >
              {product.images.map((image) => (
                <Image
                  key={image.id}
                  source={image.urls.medium}
                  contentFit="contain"
                  cachePolicy="disk"
                  accessibilityLabel={image.alt_text || product.name}
                  style={{
                    width: photo,
                    height: photo,
                    marginRight: space[3],
                    borderRadius: radius,
                    backgroundColor: colors.muted,
                  }}
                />
              ))}
            </ScrollView>
          ) : (
            <Thumb url={null} size={photo * 0.6} />
          )}
          <View style={styles.gap}>
            <Text size="2xl" weight="bold">
              {product.name}
            </Text>
            {product.brand ? (
              <View style={styles.inline}>
                <Text tone="muted" size="sm">
                  {product.brand.name}
                </Text>
                {product.own_brand ? <OwnBrandBadge /> : null}
              </View>
            ) : null}
          </View>
          <PriceBlock price={product.price} mrp={product.mrp} large />
          <Availability product={product} />
          <OrderingNote product={product} />
          {product.pack_unit && product.pack_size ? (
            <Text size="sm">
              {t("pack", {
                pack: product.pack_unit.name,
                qty: formatQty(product.pack_size),
                unit: product.unit.name,
              })}
            </Text>
          ) : null}
          {product.free_offer ? <FreeOfferDetails offer={product.free_offer} /> : null}
          {product.slab_hints.length ? (
            <Card style={{ backgroundColor: colors.success + "14" }}>
              <Text weight="semibold">{t("buyMore")}</Text>
              {product.slab_hints.map((hint) => (
                <Text key={hint.min_qty} size="sm">
                  {t("slab", { qty: formatQty(hint.min_qty) })}{" "}
                  <MoneyText value={hint.net_unit_price} size="sm" weight="semibold" />{" "}
                  {ts("price.each")}
                </Text>
              ))}
            </Card>
          ) : null}
          {product.description ? <Text size="sm">{product.description}</Text> : null}
          {/* The order box at the end, as on the web's product page. */}
          <Card accessibilityLabel={to("orderBox")}>
            <QuantityStepper product={product} disabled={!orderable(product)} wide />
            {!orderable(product) ? (
              <Text tone="muted" size="sm">
                {to("cantOrder")}
              </Text>
            ) : !isZero(quantityOf(product.id)) ? (
              <Button
                variant="outline"
                label={to("goToCart")}
                onPress={() => router.navigate("/shop/cart")}
              />
            ) : null}
          </Card>
        </Screen>
      )}
    </>
  );
}

const styles = StyleSheet.create({
  gap: { gap: space[1] },
  inline: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space[2] },
  box: { padding: space[4], gap: space[1] },
  footer: { gap: space[2] },
});
