/**
 * Messages (the web's components/shop/messages.tsx): WhatsApp on or off, and which messages come
 * on which channel (the app notification among them once this phone has the app registered), plus
 * what only the app has: the sound while it's open, and the phone's own settings for each kind.
 */
import Feather from "@expo/vector-icons/Feather";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Alert, Linking, Pressable, StyleSheet, Switch, View } from "react-native";

import { Unsaved } from "@/components/app/offline";
import { ErrorState, Skeleton } from "@/components/shared/states";
import { Card } from "@/components/ui/card";
import { Text } from "@/components/ui/text";
import { useErrorText } from "@/lib/api/error-text";
import {
  getShopNotificationPreferencesQueryKey,
  getShopWhatsappConsentQueryKey,
  shopNotificationPreferencesUpdate,
  shopWhatsappConsentPrompted,
  shopWhatsappConsentUpdate,
  useShopNotificationPreferences,
  useShopWhatsappConsent,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { NotificationChannelEnum, PreferenceRow } from "@/lib/api/generated/model";
import { useAuth } from "@/lib/auth/auth-provider";
import { useTranslations } from "@/lib/i18n/translations";
import { failed, isUnsaved, isWaiting } from "@/lib/offline/online";
import { onSoundSettingChange, setSoundSetting, soundSetting } from "@/lib/push/push";
import { space, TOUCH, useTheme } from "@/lib/theme/theme";

const labelKey = (code: string) => code.replace(".", "_");

/** A labelled switch whose whole row is the touch target (48 tall). */
function SwitchRow({
  label,
  value,
  disabled,
  onChange,
  accessibilityLabel,
}: {
  label: string;
  value: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
  accessibilityLabel?: string;
}) {
  const { colors } = useTheme();
  return (
    <Pressable
      accessibilityRole="switch"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ checked: value, disabled }}
      disabled={disabled}
      onPress={() => onChange(!value)}
      style={styles.switchRow}
    >
      <Text size="sm" style={[styles.flex, disabled && { color: colors.mutedForeground }]}>
        {label}
      </Text>
      <Switch
        value={value}
        disabled={disabled}
        onValueChange={onChange}
        // The web's switch: the brand colour when on, the input grey when off, a white knob.
        trackColor={{ true: colors.primary, false: colors.input }}
        thumbColor={colors.background}
        accessible={false}
        importantForAccessibility="no"
      />
    </Pressable>
  );
}

/** Asked once after sign-in, if the distributor sends WhatsApp messages and the shop hasn't agreed
 * yet (the web's dialog, as Android's): "Yes" records the shop's consent; "Not now" doesn't ask
 * again. */
export function WhatsAppPrompt() {
  const t = useTranslations("shop.messages");
  const { me } = useAuth();
  const client = useQueryClient();
  const { message } = useErrorText();
  const consent = useShopWhatsappConsent().data?.data;
  const asked = useRef(false);
  useEffect(() => {
    if (asked.current || !consent?.prompt || !consent.whatsapp_available) return;
    asked.current = true;
    const answer = async (agreed: boolean) => {
      try {
        const response = agreed
          ? await shopWhatsappConsentUpdate({ agreed: true })
          : await shopWhatsappConsentPrompted();
        client.setQueryData(getShopWhatsappConsentQueryKey(), response);
        if (agreed) Alert.alert(t("turnedOn"));
      } catch (error) {
        Alert.alert(message(error));
      }
    };
    Alert.alert(
      t("promptTitle"),
      t("promptBody", { distributor: me?.tenant?.name ?? "", mobile: me?.phone ?? "" }),
      [
        { text: t("promptNo"), style: "cancel", onPress: () => void answer(false) },
        { text: t("promptYes"), onPress: () => void answer(true) },
      ],
      { cancelable: true, onDismiss: () => void answer(false) },
    );
  }, [consent, client, me, message, t]);
  return null;
}

function WhatsAppCard() {
  const t = useTranslations("shop.messages");
  const { me } = useAuth();
  const client = useQueryClient();
  const { message } = useErrorText();
  const query = useShopWhatsappConsent();
  const consent = query.data?.data;
  const [busy, setBusy] = useState(false);
  if (isWaiting(query)) return <Skeleton height={96} />;
  if (failed(query)) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!consent) return null;
  const mobile = me?.phone ?? "";
  const change = async (agreed: boolean) => {
    setBusy(true);
    try {
      const response = await shopWhatsappConsentUpdate({ agreed });
      client.setQueryData(getShopWhatsappConsentQueryKey(), response);
    } catch (error) {
      Alert.alert(message(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <Text weight="semibold">{t("whatsappTitle")}</Text>
      {consent.whatsapp_available ? (
        <>
          <Text tone="muted" size="sm">
            {consent.opted_in ? t("whatsappOn", { mobile }) : t("whatsappOff", { mobile })}
          </Text>
          <SwitchRow
            label={t("whatsappSwitch")}
            value={consent.opted_in}
            disabled={busy}
            onChange={(value) => void change(value)}
          />
        </>
      ) : (
        <Text tone="muted" size="sm">
          {t("whatsappUnavailable")}
        </Text>
      )}
    </Card>
  );
}

/** What only the app has: the short sound while it's open, and the phone's own settings, where
 * each kind of message (Android's channel) can be silenced or given another sound. */
function AppCard() {
  const t = useTranslations("app.messages");
  const { colors } = useTheme();
  const [sound, setSound] = useState(soundSetting());
  useEffect(() => onSoundSettingChange(setSound), []);
  return (
    <Card>
      <Text weight="semibold">{t("appTitle")}</Text>
      <SwitchRow label={t("sound")} value={sound} onChange={(on) => void setSoundSetting(on)} />
      <Text tone="muted" size="sm">
        {t("soundBody")}
      </Text>
      <Pressable
        accessibilityRole="button"
        onPress={() => void Linking.openSettings()}
        style={styles.link}
      >
        <Feather name="settings" size={18} color={colors.primary} />
        <Text tone="primary" weight="medium" style={styles.flex}>
          {t("phoneSettings")}
        </Text>
      </Pressable>
      <Text tone="muted" size="sm">
        {t("phoneSettingsBody")}
      </Text>
    </Card>
  );
}

function PreferenceGroup({
  rows,
  whatsappOn,
  onChange,
  busy,
}: {
  rows: PreferenceRow[];
  whatsappOn: boolean;
  onChange: (event: string, channel: NotificationChannelEnum, enabled: boolean) => void;
  busy: boolean;
}) {
  const t = useTranslations("shop.messages");
  const n = useTranslations("notifications");
  const { colors, radius } = useTheme();
  return (
    <View style={[styles.list, { borderColor: colors.border, borderRadius: radius + 4 }]}>
      {rows.map((row, index) => {
        const label = n(`shopEvents.${labelKey(row.event)}`);
        return (
          <View
            key={row.event}
            style={[
              styles.event,
              index > 0 && { borderTopWidth: 1, borderTopColor: colors.border },
            ]}
          >
            <Text weight="medium">{label}</Text>
            {row.compulsory ? (
              <View style={styles.always}>
                <Feather name="lock" size={12} color={colors.mutedForeground} />
                <Text tone="muted" size="xs">
                  {t("always")}
                </Text>
              </View>
            ) : null}
            {row.channels.map((channel) => {
              const needsWhatsApp = channel.channel === "WHATSAPP" && !whatsappOn;
              const name = n(`channels.${channel.channel}`);
              return (
                <SwitchRow
                  key={channel.channel}
                  label={name}
                  accessibilityLabel={t("switchLabel", { event: label, channel: name })}
                  value={channel.enabled && !needsWhatsApp}
                  disabled={channel.locked || needsWhatsApp || busy}
                  onChange={(value) => onChange(row.event, channel.channel, value)}
                />
              );
            })}
          </View>
        );
      })}
    </View>
  );
}

/** Account → Messages. */
export function MessagesSettings() {
  const t = useTranslations("shop.messages");
  const n = useTranslations("notifications");
  const client = useQueryClient();
  const { message } = useErrorText();
  const query = useShopNotificationPreferences();
  const consent = useShopWhatsappConsent().data?.data;
  const [busy, setBusy] = useState(false);
  const rows = query.data?.data ?? [];
  const groups = [...new Set(rows.map((r) => r.group))];

  const change = async (event: string, channel: NotificationChannelEnum, enabled: boolean) => {
    setBusy(true);
    try {
      const response = await shopNotificationPreferencesUpdate({ event, channel, enabled });
      client.setQueryData(getShopNotificationPreferencesQueryKey(), response);
    } catch (error) {
      Alert.alert(message(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <View style={styles.head}>
        <Text size="2xl" weight="bold">
          {t("title")}
        </Text>
        <Text tone="muted" size="sm">
          {t("body")}
        </Text>
      </View>
      <WhatsAppCard />
      <AppCard />
      {isWaiting(query) ? (
        <Skeleton height={160} />
      ) : isUnsaved(query) ? (
        <Unsaved />
      ) : failed(query) ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <Text tone="muted" size="sm">
            {t("alwaysHint")}
          </Text>
          {groups.map((group) => (
            <View key={group} style={styles.group}>
              <Text size="lg" weight="semibold">
                {n(`groups.${group}`)}
              </Text>
              <PreferenceGroup
                rows={rows.filter((r) => r.group === group)}
                whatsappOn={Boolean(consent?.opted_in && consent.whatsapp_available)}
                onChange={(event, channel, enabled) => void change(event, channel, enabled)}
                busy={busy}
              />
            </View>
          ))}
        </>
      )}
    </>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  head: { gap: space[1] },
  group: { gap: space[2] },
  list: { borderWidth: 1 },
  event: { padding: space[4], gap: 2 },
  always: { flexDirection: "row", alignItems: "center", gap: 4 },
  switchRow: { minHeight: TOUCH, flexDirection: "row", alignItems: "center", gap: space[3] },
  link: { minHeight: TOUCH, flexDirection: "row", alignItems: "center", gap: space[2] },
});
