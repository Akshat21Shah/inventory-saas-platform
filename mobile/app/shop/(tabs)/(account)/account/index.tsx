/**
 * My account (the web's /shop/account): what the shop owes and paying it, then the money pages,
 * its returns, messages (WhatsApp, the app's notifications and sound), profile, delivery
 * addresses, help, privacy and data, switching distributor and signing out (owner, checkpoint
 * review item 5).
 */
import Feather from "@expo/vector-icons/Feather";
import { Link } from "expo-router";
import type { ComponentProps } from "react";
import { Pressable, StyleSheet, View } from "react-native";

import { confirm } from "@/components/shared/confirm";
import { ErrorState, Skeleton } from "@/components/shared/states";
import { AccountMoney } from "@/components/shop/money";
import { Button } from "@/components/ui/button";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useShopAccount } from "@/lib/api/generated/endpoints/shop/shop";
import { useAuth } from "@/lib/auth/auth-provider";
import { APP_VERSION, config } from "@/lib/config";
import { useTranslations } from "@/lib/i18n/translations";
import { space, useTheme } from "@/lib/theme/theme";

type Icon = ComponentProps<typeof Feather>["name"];

export default function AccountTab() {
  const t = useTranslations("shop.money");
  const tr = useTranslations("shop.returns");
  const ta = useTranslations("app.account");
  const tc = useTranslations("shop.account");
  const auth = useTranslations("auth");
  const common = useTranslations("common");
  const { signOut } = useAuth();
  const { colors, radius } = useTheme();
  const query = useShopAccount();
  const account = query.data?.data;
  const menu: { href: string; label: string; icon: Icon }[] = [
    { href: "/shop/invoices", label: t("bills"), icon: "file-text" },
    { href: "/shop/statement", label: t("statement"), icon: "book-open" },
    { href: "/shop/payments", label: t("payments"), icon: "credit-card" },
    { href: "/shop/returns", label: tr("heading"), icon: "rotate-ccw" },
    { href: "/shop/account/messages", label: t("messages"), icon: "bell" },
    { href: "/shop/account/profile", label: t("profile"), icon: "user" },
    { href: "/shop/account/addresses", label: tc("addresses.title"), icon: "map-pin" },
    { href: "/shop/account/help", label: tc("help.title"), icon: "life-buoy" },
    { href: "/shop/account/privacy", label: tc("privacy.title"), icon: "shield" },
  ];
  return (
    <Screen refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
      <Text size="2xl" weight="bold">
        {t("title")}
      </Text>
      {query.isLoading ? (
        <Skeleton height={140} />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : account ? (
        <AccountMoney account={account} />
      ) : null}
      <View
        accessibilityLabel={t("menu")}
        style={[styles.menu, { borderColor: colors.border, borderRadius: radius + 4 }]}
      >
        {menu.map((item, index) => (
          <Link key={item.href} href={item.href} asChild>
            <Pressable
              accessibilityRole="link"
              style={StyleSheet.flatten([
                styles.item,
                index > 0 && { borderTopWidth: 1, borderTopColor: colors.border },
              ])}
            >
              <Feather name={item.icon} size={20} color={colors.mutedForeground} />
              <Text weight="medium" style={styles.flex}>
                {item.label}
              </Text>
              <Feather name="chevron-right" size={20} color={colors.mutedForeground} />
            </Pressable>
          </Link>
        ))}
      </View>
      <Button
        variant="outline"
        label={ta("switch")}
        icon={<Feather name="repeat" size={16} color={colors.foreground} />}
        onPress={() =>
          confirm({
            title: ta("switch"),
            body: ta("switchBody"),
            confirmLabel: ta("switch"),
            cancelLabel: common("cancel"),
            onConfirm: signOut,
          })
        }
      />
      <Button
        variant="outline"
        label={auth("signOut")}
        icon={<Feather name="log-out" size={16} color={colors.foreground} />}
        onPress={() =>
          confirm({
            title: auth("signOut"),
            confirmLabel: auth("signOut"),
            cancelLabel: common("cancel"),
            onConfirm: signOut,
          })
        }
      />
      <Text tone="muted" size="xs" style={styles.centre}>
        {ta("version", { version: APP_VERSION, build: config.build })}
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  menu: { borderWidth: 1 },
  item: {
    minHeight: 56,
    paddingHorizontal: space[4],
    flexDirection: "row",
    alignItems: "center",
    gap: space[3],
  },
  centre: { textAlign: "center" },
});
