import { FlashList } from "@shopify/flash-list";
import { useInfiniteQuery } from "@tanstack/react-query";
import { router } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";

import { Unsaved } from "@/components/app/offline";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/shared/states";
import { OrderRowLink } from "@/components/shop/order-row";
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import { shopOrdersList } from "@/lib/api/generated/endpoints/shop/shop";
import type { ShopOrdersListState } from "@/lib/api/generated/model";
import { useTranslations } from "@/lib/i18n/translations";
import { failed, isUnsaved, isWaiting } from "@/lib/offline/online";
import { space, TOUCH, useTheme } from "@/lib/theme/theme";

function cursorOf(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  return new URL(url, "http://localhost").searchParams.get("cursor") ?? undefined;
}

export default function OrdersTab() {
  const t = useTranslations("shop.orders");
  const { colors } = useTheme();
  const [state, setState] = useState<ShopOrdersListState>("open");
  const query = useInfiniteQuery({
    queryKey: ["/api/v1/shop/orders/", "infinite", state],
    queryFn: ({ pageParam, signal }) => shopOrdersList({ state, cursor: pageParam }, { signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => cursorOf(last.data.next),
  });
  const orders = query.data?.pages.flatMap((page) => page.data.results) ?? [];
  const tabs = (
    <View style={styles.header}>
      <Text size="2xl" weight="bold">
        {t("title")}
      </Text>
      <View style={styles.tabs} accessibilityRole="tablist" accessibilityLabel={t("show")}>
        {(["open", "closed"] as const).map((value) => {
          const on = state === value;
          return (
            <Pressable
              key={value}
              accessibilityRole="tab"
              accessibilityState={{ selected: on }}
              onPress={() => setState(value)}
              style={[
                styles.tab,
                {
                  borderColor: on ? colors.brand200 : colors.border,
                  backgroundColor: on ? colors.brand50 : "transparent",
                },
              ]}
            >
              <Text size="sm" weight={on ? "semibold" : "normal"}>
                {t(value)}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
  return (
    <FlashList
      data={orders}
      keyExtractor={(order) => order.id}
      renderItem={({ item }) => (
        <View style={styles.item}>
          <OrderRowLink order={item} />
        </View>
      )}
      ListHeaderComponent={tabs}
      ListEmptyComponent={
        isWaiting(query) ? (
          <ListSkeleton />
        ) : isUnsaved(query) ? (
          <Unsaved />
        ) : failed(query) ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <EmptyState
            icon="clipboard"
            title={state === "open" ? t("noneOpen") : t("noneClosed")}
            body={t("noneBody")}
            action={{ label: t("browse"), onPress: () => router.push("/shop/catalog") }}
          />
        )
      }
      ListFooterComponent={
        query.hasNextPage ? (
          <Button
            variant="outline"
            label={t("showMore")}
            busy={query.isFetchingNextPage}
            onPress={() => void query.fetchNextPage()}
          />
        ) : null
      }
      refreshing={query.isRefetching && !query.isFetchingNextPage}
      onRefresh={() => void query.refetch()}
      contentContainerStyle={styles.content}
    />
  );
}

const styles = StyleSheet.create({
  content: { padding: space[4], paddingBottom: space[8] },
  header: { gap: space[3], marginBottom: space[4] },
  tabs: { flexDirection: "row", gap: space[2] },
  tab: {
    minHeight: TOUCH,
    paddingHorizontal: space[4],
    borderWidth: 1,
    borderRadius: 999,
    justifyContent: "center",
  },
  item: { marginBottom: space[2] },
});
