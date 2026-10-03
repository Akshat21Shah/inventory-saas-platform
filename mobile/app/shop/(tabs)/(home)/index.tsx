import Feather from "@expo/vector-icons/Feather";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, router } from "expo-router";
import { Alert, Pressable, StyleSheet, View } from "react-native";

import { EmptyState, ErrorState, ListSkeleton } from "@/components/shared/states";
import { DateText } from "@/components/shared/values";
import { CategoryTiles } from "@/components/shop/catalog";
import { OwedCard } from "@/components/shop/money";
import { OrderRowLink } from "@/components/shop/order-row";
import { OnHoldNotice, ProductCard } from "@/components/shop/product";
import { SearchEntry } from "@/components/shop/search-box";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useErrorText } from "@/lib/api/error-text";
import {
  getShopCartRetrieveQueryKey,
  shopOrderRepeat,
  useShopAnnouncements,
  useShopCategories,
  useShopHome,
} from "@/lib/api/generated/endpoints/shop/shop";
import { useAuth } from "@/lib/auth/auth-provider";
import { useTranslations } from "@/lib/i18n/translations";
import { space, useTheme } from "@/lib/theme/theme";

function Announcements() {
  const query = useShopAnnouncements();
  const { colors } = useTheme();
  const items = query.data?.data ?? [];
  if (!items.length) return null;
  return (
    <View style={styles.gap}>
      {items.map((item) => (
        <Card
          key={item.id}
          style={{ backgroundColor: colors.brand50, borderColor: colors.brand200 }}
        >
          <View style={styles.inline}>
            <Feather name="volume-2" size={16} color={colors.brand800} />
            <Text weight="semibold" style={{ color: colors.brand800 }}>
              {item.title}
            </Text>
          </View>
          <Text size="sm">{item.body}</Text>
        </Card>
      ))}
    </View>
  );
}

function RepeatLastOrder() {
  const t = useTranslations("shop.home");
  const home = useShopHome();
  const client = useQueryClient();
  const { message } = useErrorText();
  const { colors } = useTheme();
  const last = home.data?.data.last_order;
  const repeat = useMutation({
    mutationFn: (orderId: string) => shopOrderRepeat(orderId),
    onSuccess: (response) => {
      client.setQueryData(getShopCartRetrieveQueryKey(), { ...response, data: response.data.cart });
      const skipped = response.data.skipped;
      if (skipped.length) {
        Alert.alert(
          t("skipped", { count: skipped.length, names: skipped.map((s) => s.name).join(", ") }),
        );
      }
      router.push("/shop/cart");
    },
    onError: (error) => Alert.alert(message(error)),
  });
  if (home.isLoading) return <ListSkeleton rows={2} />;
  if (home.error) return <ErrorState error={home.error} onRetry={() => void home.refetch()} />;
  if (!last || last.items.length === 0) return null;
  return (
    <View style={styles.gap}>
      <View style={styles.gapXs}>
        <Text size="lg" weight="semibold">
          {t("repeatTitle")}
        </Text>
        <Text tone="muted" size="xs">
          {t("repeatFrom", { number: last.number })} ·{" "}
          <DateText value={last.placed_at} tone="muted" size="xs" />
        </Text>
      </View>
      <Button
        variant="outline"
        label={t("repeatAll")}
        busy={repeat.isPending}
        icon={<Feather name="rotate-ccw" size={16} color={colors.foreground} />}
        onPress={() => repeat.mutate(last.id)}
      />
      {last.items.map((item) => (
        <ProductCard key={item.id} product={item} lastQuantity={item.last_quantity} />
      ))}
    </View>
  );
}

function RecentOrders() {
  const t = useTranslations("shop.home");
  const home = useShopHome();
  const data = home.data?.data;
  if (home.isLoading || home.error || !data) return null;
  if (data.recent_orders.length === 0) {
    return <EmptyState icon="clipboard" title={t("noOrdersTitle")} body={t("noOrdersBody")} />;
  }
  return (
    <View style={styles.gap}>
      <View style={styles.between}>
        <Text size="lg" weight="semibold" style={styles.flex}>
          {t("recentTitle")}
        </Text>
        <SeeAll href="/shop/orders" label={t("allOrders")} />
      </View>
      {data.open_orders || data.waiting_items ? (
        <Text tone="muted" size="sm">
          {t("summary", { open: data.open_orders, waiting: data.waiting_items })}
        </Text>
      ) : null}
      {data.recent_orders.map((order) => (
        <OrderRowLink key={order.id} order={order} />
      ))}
    </View>
  );
}

function SeeAll({ href, label }: { href: "/shop/orders" | "/shop/catalog"; label: string }) {
  const { colors } = useTheme();
  return (
    <Link href={href} asChild>
      <Pressable accessibilityRole="link" style={styles.link}>
        <Text weight="medium" size="sm" style={{ color: colors.brand700 }}>
          {label}
        </Text>
      </Pressable>
    </Link>
  );
}

export default function Home() {
  const t = useTranslations("shop");
  const { me } = useAuth();
  const home = useShopHome();
  const categories = useShopCategories();
  const tree = categories.data?.data ?? [];
  return (
    <Screen
      refreshing={home.isRefetching}
      onRefresh={() => {
        void home.refetch();
        void categories.refetch();
      }}
    >
      <View style={styles.gap}>
        <Text size="2xl" weight="bold">
          {me?.retailer ? t("hello", { shop: me.retailer.shop_name }) : t("catalogTitle")}
        </Text>
        <Text tone="muted" size="sm">
          {t("homeBody")}
        </Text>
      </View>
      <Announcements />
      <OnHoldNotice />
      <OwedCard />
      <SearchEntry />
      <RepeatLastOrder />
      <RecentOrders />
      <View style={styles.gap}>
        <View style={styles.between}>
          <Text size="lg" weight="semibold" style={styles.flex}>
            {t("categories")}
          </Text>
          <SeeAll href="/shop/catalog" label={t("allProducts")} />
        </View>
        {categories.isLoading ? (
          <ListSkeleton rows={2} />
        ) : categories.error ? (
          <ErrorState error={categories.error} onRetry={() => void categories.refetch()} />
        ) : (
          <CategoryTiles categories={tree} />
        )}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  gap: { gap: space[3] },
  gapXs: { gap: space[1] },
  flex: { flex: 1 },
  inline: { flexDirection: "row", alignItems: "center", gap: space[2] },
  between: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: space[2],
    flexWrap: "wrap",
  },
  link: { minHeight: 48, justifyContent: "center" },
});
