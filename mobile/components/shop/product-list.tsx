/**
 * Products from the server, 30 at a time, in a virtualised list (budget phones, ADR-061 item 12),
 * with whatever the screen shows above them.
 */
import { FlashList } from "@shopify/flash-list";
import { useInfiniteQuery } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { StyleSheet, View } from "react-native";

import { OfflineBanner, Unsaved } from "@/components/app/offline";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { shopProducts } from "@/lib/api/generated/endpoints/shop/shop";
import type { ShopProductsParams } from "@/lib/api/generated/model";
import { useTranslations } from "@/lib/i18n/translations";
import { useOnline, failed, isUnsaved, isWaiting } from "@/lib/offline/online";
import { space } from "@/lib/theme/theme";

import { ProductCard } from "./product";

function cursorOf(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  return new URL(url, "http://localhost").searchParams.get("cursor") ?? undefined;
}

export function ProductList({
  params,
  header,
}: {
  params: ShopProductsParams;
  header?: ReactElement;
}) {
  const t = useTranslations("shop");
  const online = useOnline();
  const query = useInfiniteQuery({
    queryKey: ["/api/v1/shop/products/", "infinite", params],
    queryFn: ({ pageParam, signal }) => shopProducts({ ...params, cursor: pageParam }, { signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => cursorOf(last.data.next),
  });
  const products = query.data?.pages.flatMap((page) => page.data.results) ?? [];
  const empty = isWaiting(query) ? (
    <ListSkeleton />
  ) : isUnsaved(query) ? (
    <Unsaved />
  ) : failed(query) ? (
    <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  ) : (
    <EmptyState
      icon="search"
      title={params.search ? t("noMatchTitle") : t("noProductsTitle")}
      body={params.search ? t("noMatchBody") : t("noProductsBody")}
    />
  );
  return (
    <FlashList
      data={products}
      keyExtractor={(product) => product.id}
      renderItem={({ item }) => (
        <View style={styles.item}>
          <ProductCard product={item} />
        </View>
      )}
      ListHeaderComponent={
        header || !online ? (
          <View style={styles.header}>
            <OfflineBanner />
            {header}
          </View>
        ) : null
      }
      ListEmptyComponent={empty}
      ListFooterComponent={
        query.hasNextPage ? (
          <View style={styles.item}>
            <Button
              variant="outline"
              label={t("showMore")}
              busy={query.isFetchingNextPage}
              onPress={() => void query.fetchNextPage()}
            />
          </View>
        ) : null
      }
      refreshing={query.isRefetching && !query.isFetchingNextPage}
      onRefresh={() => void query.refetch()}
      contentContainerStyle={styles.content}
      // A tap on a result works with the keyboard up; a tap on empty space or scrolling closes it.
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode="on-drag"
    />
  );
}

const styles = StyleSheet.create({
  content: { padding: space[4], paddingBottom: space[8] },
  header: { gap: space[4], marginBottom: space[4] },
  item: { marginBottom: space[3] },
});
