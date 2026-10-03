/** Saved delivery addresses (owner, checkpoint review item 5): to see them; the distributor adds
 * and changes them, as on the web. */
import { StyleSheet, View } from "react-native";

import { EmptyState, ErrorState, ListSkeleton } from "@/components/shared/states";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useShopAddressesList } from "@/lib/api/generated/endpoints/shop/shop";
import { useTranslations } from "@/lib/i18n/translations";
import { space } from "@/lib/theme/theme";

export default function AddressesScreen() {
  const t = useTranslations("shop.account.addresses");
  const query = useShopAddressesList();
  const list = query.data?.data ?? [];
  return (
    <Screen refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
      <View style={styles.head}>
        <Text size="2xl" weight="bold">
          {t("title")}
        </Text>
        <Text tone="muted" size="sm">
          {t("body")}
        </Text>
      </View>
      {query.isLoading ? (
        <ListSkeleton rows={2} />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : list.length === 0 ? (
        <EmptyState icon="map-pin" title={t("none")} />
      ) : (
        list.map((address) => (
          <Card key={address.id}>
            <View style={styles.between}>
              <Text weight="medium" style={styles.flex}>
                {address.name}
              </Text>
              {address.is_default ? <Badge tone="brand" label={t("default")} /> : null}
            </View>
            <Text size="sm">{[address.line1, address.line2].filter(Boolean).join(", ")}</Text>
            <Text tone="muted" size="sm">
              {[address.city, address.state, address.pincode].filter(Boolean).join(", ")}
            </Text>
          </Card>
        ))
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  head: { gap: space[1] },
  between: { flexDirection: "row", alignItems: "center", gap: space[2] },
});
