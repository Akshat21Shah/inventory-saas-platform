/** Help (owner, checkpoint review item 5): the distributor's phone and email, to call, write on
 * WhatsApp or email about orders, bills and payments. */
import Feather from "@expo/vector-icons/Feather";
import { Linking, StyleSheet, View } from "react-native";

import { ErrorState, Skeleton } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useShopDistributor } from "@/lib/api/generated/endpoints/shop/shop";
import { useTranslations } from "@/lib/i18n/translations";
import { space, useTheme } from "@/lib/theme/theme";

/** A phone number as WhatsApp's link wants it: digits only, with India's 91. */
function whatsappNumber(phone: string): string {
  const digits = phone.replace(/\D/g, "");
  return digits.length === 10 ? `91${digits}` : digits;
}

export default function HelpScreen() {
  const t = useTranslations("shop.account.help");
  const { colors } = useTheme();
  const query = useShopDistributor();
  const distributor = query.data?.data;
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
        <Skeleton height={140} />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : distributor ? (
        <Card>
          <Text size="lg" weight="semibold">
            {distributor.name}
          </Text>
          {distributor.phone ? (
            <>
              <Text tone="muted" size="sm">
                {distributor.phone}
              </Text>
              <Button
                label={t("call")}
                icon={<Feather name="phone" size={16} color={colors.primaryForeground} />}
                onPress={() => void Linking.openURL(`tel:${distributor.phone}`)}
              />
              <Button
                variant="outline"
                label={t("whatsapp")}
                icon={<Feather name="message-circle" size={16} color={colors.foreground} />}
                onPress={() =>
                  void Linking.openURL(`https://wa.me/${whatsappNumber(distributor.phone)}`)
                }
              />
            </>
          ) : null}
          {distributor.email ? (
            <>
              <Text tone="muted" size="sm">
                {distributor.email}
              </Text>
              <Button
                variant="outline"
                label={t("email")}
                icon={<Feather name="mail" size={16} color={colors.foreground} />}
                onPress={() => void Linking.openURL(`mailto:${distributor.email}`)}
              />
            </>
          ) : null}
          {!distributor.phone && !distributor.email ? (
            <Text tone="muted" size="sm">
              {t("noContact")}
            </Text>
          ) : null}
        </Card>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({ head: { gap: space[1] } });
