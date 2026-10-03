/** Return items (the web's dialog on a bill, ADR-057 item 3): quantities up to what may still be
 * returned, and why. Nothing moves until the distributor approves. */
import Feather from "@expo/vector-icons/Feather";
import { useQueryClient } from "@tanstack/react-query";
import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Alert, Pressable, StyleSheet, TextInput, View } from "react-native";

import { Unsaved } from "@/components/app/offline";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useErrorText } from "@/lib/api/error-text";
import {
  getShopInvoicesRetrieveQueryKey,
  shopReturnRequestsCreate,
  useShopInvoicesRetrieve,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { ReturnReasonEnum } from "@/lib/api/generated/model";
import { useTranslations } from "@/lib/i18n/translations";
import { failed, isUnsaved, isWaiting } from "@/lib/offline/online";
import { formatQty } from "@/lib/shared/format";
import { space, text, TOUCH, useTheme } from "@/lib/theme/theme";

const REASONS: ReturnReasonEnum[] = ["DAMAGED", "EXPIRED", "WRONG_ITEM", "EXCESS_SUPPLY", "OTHER"];

export default function ReturnScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const t = useTranslations("shop.returns");
  const tm = useTranslations("shop.money");
  const errors = useErrorText();
  const client = useQueryClient();
  const { colors, radius } = useTheme();
  const query = useShopInvoicesRetrieve(id);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [reason, setReason] = useState<ReturnReasonEnum>("DAMAGED");
  const [note, setNote] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const bill = query.data?.data;

  if (isWaiting(query)) {
    return (
      <Screen>
        <ListSkeleton />
      </Screen>
    );
  }
  if (isUnsaved(query)) {
    return (
      <Screen>
        <Unsaved />
      </Screen>
    );
  }
  if (failed(query) || !bill) {
    return (
      <Screen>
        {query.error ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <EmptyState icon="file-text" title={tm("notFound")} />
        )}
      </Screen>
    );
  }
  const left = new Map(bill.returnable.map((row) => [row.invoice_line_id, row.quantity]));
  const lines = bill.lines.filter((line) => Number(left.get(line.id) ?? 0) > 0);
  const chosen = Object.entries(quantities).filter(([, q]) => Number(q) > 0);

  async function send() {
    setBusy(true);
    setFieldErrors({});
    try {
      await shopReturnRequestsCreate({
        invoice: id,
        reason,
        note: note.trim(),
        lines: chosen.map(([line, quantity]) => ({ invoice_line: line, quantity })),
      });
      await client.invalidateQueries({ queryKey: getShopInvoicesRetrieveQueryKey(id) });
      Alert.alert(t("sent"));
      router.back();
    } catch (error) {
      const fields = errors.fields(error);
      setFieldErrors(fields);
      if (Object.keys(fields).length === 0) Alert.alert(errors.message(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen
      footer={
        <View style={styles.actions}>
          <Button variant="outline" label={t("cancel")} onPress={() => router.back()} />
          <Button
            label={t("send")}
            needsInternet
            busy={busy}
            disabled={chosen.length === 0}
            onPress={() => void send()}
            style={styles.flex}
          />
        </View>
      }
    >
      <View style={styles.head}>
        <Text size="2xl" weight="bold">
          {t("title")}
        </Text>
        <Text tone="muted">{t("body")}</Text>
      </View>
      <Card>
        {lines.map((line) => (
          <View key={line.id} style={styles.line}>
            <View style={styles.flex}>
              <Text weight="medium">{line.description}</Text>
              <Text tone="muted" size="xs">
                {t("upTo", { qty: formatQty(left.get(line.id) ?? "0"), unit: line.unit_code })}
              </Text>
            </View>
            <TextInput
              accessibilityLabel={line.description}
              keyboardType="decimal-pad"
              placeholder="0"
              placeholderTextColor={colors.mutedForeground}
              value={quantities[line.id] ?? ""}
              onChangeText={(value) => setQuantities((q) => ({ ...q, [line.id]: value }))}
              style={[
                styles.qty,
                { borderColor: colors.input, borderRadius: radius, color: colors.foreground },
              ]}
            />
          </View>
        ))}
        {fieldErrors.lines ? (
          <Text tone="danger" size="sm" weight="medium" accessibilityRole="alert">
            {fieldErrors.lines}
          </Text>
        ) : null}
      </Card>
      <View style={styles.group} accessibilityRole="radiogroup" accessibilityLabel={t("reason")}>
        <Text weight="medium">{t("reason")}</Text>
        {REASONS.map((code) => {
          const on = reason === code;
          return (
            <Pressable
              key={code}
              accessibilityRole="radio"
              accessibilityState={{ selected: on }}
              onPress={() => setReason(code)}
              style={[
                styles.option,
                { borderColor: on ? colors.primary : colors.border, borderRadius: radius },
              ]}
            >
              <Feather
                name={on ? "check-circle" : "circle"}
                size={18}
                color={on ? colors.primary : colors.mutedForeground}
              />
              <Text>{t(`reasons.${code}`)}</Text>
            </Pressable>
          );
        })}
        {fieldErrors.reason ? (
          <Text tone="danger" size="sm">
            {fieldErrors.reason}
          </Text>
        ) : null}
      </View>
      <Input
        label={t("note")}
        hint={t("noteHint")}
        error={fieldErrors.note}
        value={note}
        maxLength={500}
        multiline
        onChangeText={setNote}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  head: { gap: space[1] },
  actions: { flexDirection: "row", gap: space[2] },
  line: { flexDirection: "row", alignItems: "center", gap: space[3] },
  qty: {
    width: 96,
    height: TOUCH,
    borderWidth: 1,
    textAlign: "right",
    paddingHorizontal: space[3],
    fontSize: text.base,
  },
  group: { gap: space[2] },
  option: {
    minHeight: TOUCH,
    borderWidth: 1,
    paddingHorizontal: space[3],
    flexDirection: "row",
    alignItems: "center",
    gap: space[2],
  },
});
