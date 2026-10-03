/** Statement (the web's /shop/statement): bills, payments and credits in date order with the
 * balance after each, between two dates the shop picks (the server's defaults first). */
import Feather from "@expo/vector-icons/Feather";
import { DateTimePickerAndroid } from "@react-native-community/datetimepicker";
import { useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";

import { Unsaved } from "@/components/app/offline";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/shared/states";
import { DateText, MoneyText } from "@/components/shared/values";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useShopLedger } from "@/lib/api/generated/endpoints/shop/shop";
import { useTranslations } from "@/lib/i18n/translations";
import { failed, isUnsaved, isWaiting } from "@/lib/offline/online";
import { formatDate } from "@/lib/shared/format";
import { space, TOUCH, useTheme } from "@/lib/theme/theme";

/** "2026-10-04" ⇄ the picker's date, on the phone's calendar (a date has no time zone here). */
function toPicker(value: string): Date {
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y!, m! - 1, d!);
}
function fromPicker(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function DateField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const { colors, radius } = useTheme();
  return (
    <View style={styles.field}>
      <Text size="sm">{label}</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${label}: ${formatDate(value)}`}
        onPress={() =>
          DateTimePickerAndroid.open({
            value: toPicker(value),
            mode: "date",
            onChange: (event, date) => {
              if (event.type === "set" && date) onChange(fromPicker(date));
            },
          })
        }
        style={[styles.date, { borderColor: colors.input, borderRadius: radius }]}
      >
        <Text>{formatDate(value)}</Text>
        <Feather name="calendar" size={18} color={colors.mutedForeground} />
      </Pressable>
    </View>
  );
}

export default function StatementScreen() {
  const t = useTranslations("shop.money");
  const entries = useTranslations("billing.entryTypes");
  const { colors, radius } = useTheme();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const query = useShopLedger({ date_from: from || undefined, date_to: to || undefined });
  const statement = query.data?.data;
  const box = { borderColor: colors.border, borderRadius: radius + 4 };
  return (
    <Screen refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
      <Text size="2xl" weight="bold">
        {t("statement")}
      </Text>
      <Text tone="muted" size="sm">
        {t("statementBody")}
      </Text>
      {isWaiting(query) ? (
        <ListSkeleton rows={3} />
      ) : isUnsaved(query) ? (
        <Unsaved />
      ) : failed(query) ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : statement ? (
        <>
          <View style={styles.dates}>
            <DateField label={t("from")} value={from || statement.date_from} onChange={setFrom} />
            <DateField label={t("to")} value={to || statement.date_to} onChange={setTo} />
          </View>
          <View style={[styles.total, box]}>
            <Text size="sm">{t("balanceOn", { date: formatDate(statement.date_from) })}</Text>
            <MoneyText value={statement.opening_balance} size="sm" weight="medium" />
          </View>
          {statement.lines.length === 0 ? (
            <EmptyState icon="book-open" title={t("noEntries")} />
          ) : (
            <View style={[styles.list, box]}>
              {statement.lines.map((line, index) => (
                <View
                  key={line.id}
                  style={[
                    styles.line,
                    index > 0 && { borderTopWidth: 1, borderTopColor: colors.border },
                  ]}
                >
                  <View style={styles.between}>
                    <Text size="sm" weight="medium" style={styles.flex}>
                      {`${entries(line.entry_type)} ${line.reference_number}`}
                    </Text>
                    {line.debit !== "0.00" ? (
                      <MoneyText value={line.debit} size="sm" />
                    ) : (
                      <Text size="sm" tone="success">
                        −<MoneyText value={line.credit} size="sm" tone="success" />
                      </Text>
                    )}
                  </View>
                  <View style={styles.between}>
                    <DateText value={line.entry_date} size="xs" tone="muted" />
                    <Text size="xs" tone="muted">
                      {`${t("balance")} `}
                      <MoneyText value={line.balance} size="xs" tone="muted" />
                    </Text>
                  </View>
                </View>
              ))}
            </View>
          )}
          <View style={[styles.total, box]}>
            <Text size="sm" weight="semibold">
              {t("balanceOn", { date: formatDate(statement.date_to) })}
            </Text>
            <MoneyText value={statement.closing_balance} size="sm" weight="semibold" />
          </View>
        </>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  dates: { flexDirection: "row", gap: space[3] },
  field: { flex: 1, gap: space[1] },
  date: {
    minHeight: TOUCH,
    borderWidth: 1,
    paddingHorizontal: space[3],
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  total: {
    borderWidth: 1,
    paddingHorizontal: space[4],
    paddingVertical: space[3],
    flexDirection: "row",
    justifyContent: "space-between",
    gap: space[3],
  },
  list: { borderWidth: 1 },
  line: { padding: space[3], gap: 2 },
  between: { flexDirection: "row", justifyContent: "space-between", gap: space[3] },
});
