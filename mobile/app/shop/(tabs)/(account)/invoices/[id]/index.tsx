/** One bill (the web's /shop/invoices/[id]): what is left to pay, paying it, the PDF, the items,
 * returns and credit notes. */
import Feather from "@expo/vector-icons/Feather";
import { useQueryClient } from "@tanstack/react-query";
import { router, useLocalSearchParams } from "expo-router";
import type { ReactNode } from "react";
import { Alert, StyleSheet, View } from "react-native";

import { confirm } from "@/components/shared/confirm";
import { DocumentButton } from "@/components/shared/document-button";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/shared/states";
import { StatusBadge } from "@/components/shared/status-badge";
import { DateText, MoneyText } from "@/components/shared/values";
import { FreeLineLabel } from "@/components/shop/cart";
import { PayBillButton } from "@/components/shop/money";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useErrorText } from "@/lib/api/error-text";
import {
  getShopInvoicesRetrieveQueryKey,
  shopCreditNotesPdf,
  shopInvoicesPdf,
  shopReturnRequestsCancel,
  useShopInvoicesRetrieve,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { ShopInvoiceDetail } from "@/lib/api/generated/model";
import { useTranslations } from "@/lib/i18n/translations";
import { formatDate, formatQty } from "@/lib/shared/format";
import { space, useTheme } from "@/lib/theme/theme";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <View style={styles.section}>
      <Text weight="semibold">{title}</Text>
      {children}
    </View>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <View style={styles.between}>
      <Text size="sm">{label}</Text>
      {children}
    </View>
  );
}

/** The bill's return requests: what was asked, where it stands, and withdrawing while it waits. */
function BillReturns({ bill }: { bill: ShopInvoiceDetail }) {
  const t = useTranslations("shop.returns");
  const common = useTranslations("common");
  const client = useQueryClient();
  const { message } = useErrorText();
  if (bill.return_requests.length === 0) return null;
  return (
    <Section title={t("heading")}>
      {bill.return_requests.map((request) => (
        <Card key={request.id}>
          <View style={styles.between}>
            <Text weight="medium">{request.number}</Text>
            <StatusBadge status={request.status} labels="shopReturnStatus" />
          </View>
          <Text tone="muted" size="sm">
            {request.lines
              .map((line) => `${formatQty(line.quantity)} ${line.description}`)
              .join(", ")}
          </Text>
          {request.status === "REJECTED" && request.decision_note ? (
            <Text size="sm">{t("why", { reason: request.decision_note })}</Text>
          ) : null}
          {request.credit_note ? (
            <Text size="sm">{t("credited", { number: request.credit_note.number })}</Text>
          ) : null}
          {request.status === "REQUESTED" ? (
            <Button
              variant="outline"
              label={t("withdraw")}
              onPress={() =>
                confirm({
                  title: t("withdrawTitle", { number: request.number }),
                  confirmLabel: t("withdraw"),
                  cancelLabel: common("cancel"),
                  onConfirm: async () => {
                    try {
                      await shopReturnRequestsCancel(request.id);
                    } catch (error) {
                      Alert.alert(message(error));
                    }
                    await client.invalidateQueries({
                      queryKey: getShopInvoicesRetrieveQueryKey(bill.id),
                    });
                  },
                })
              }
            />
          ) : null}
        </Card>
      ))}
    </Section>
  );
}

export default function BillScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const t = useTranslations("shop.money");
  const tr = useTranslations("shop.returns");
  const { colors, radius } = useTheme();
  const query = useShopInvoicesRetrieve(id);
  const bill = query.data?.data;
  if (query.isLoading) {
    return (
      <Screen>
        <ListSkeleton />
      </Screen>
    );
  }
  if (query.error) {
    return (
      <Screen>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Screen>
    );
  }
  if (!bill) {
    return (
      <Screen>
        <EmptyState icon="file-text" title={t("notFound")} />
      </Screen>
    );
  }
  const left = new Map(bill.returnable.map((row) => [row.invoice_line_id, row.quantity]));
  const canReturn =
    bill.can_request_return && bill.lines.some((line) => Number(left.get(line.id) ?? 0) > 0);
  return (
    <Screen refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
      <View style={styles.head}>
        <View style={styles.wrap}>
          <Text size="2xl" weight="bold">
            {t("billHeading", { number: bill.number })}
          </Text>
          <StatusBadge status={bill.status === "CANCELLED" ? "CANCELLED" : bill.payment_status} />
        </View>
        <Text tone="muted" size="sm">
          {formatDate(bill.invoice_date)} · {t("forOrder", { number: bill.order.number })}
        </Text>
      </View>
      <Card>
        <View style={styles.between}>
          <Text size="lg" weight="semibold">
            {t("stillToPay")}
          </Text>
          <MoneyText value={bill.balance_due} size="lg" weight="semibold" />
        </View>
        {bill.balance_due !== "0.00" ? (
          <Text size="sm" tone={bill.days_overdue > 0 ? "danger" : "default"}>
            {bill.days_overdue > 0
              ? t("daysLate", { days: bill.days_overdue })
              : t("dueOn", { date: formatDate(bill.due_date) })}
          </Text>
        ) : null}
        {bill.status === "CANCELLED" ? (
          <Text
            size="sm"
            style={[styles.notice, { backgroundColor: colors.muted, borderRadius: radius }]}
          >
            {t("billCancelled")}
          </Text>
        ) : null}
        {bill.status === "ISSUED" ? (
          <PayBillButton invoiceId={bill.id} balance={bill.balance_due} />
        ) : null}
        <DocumentButton
          label={t("downloadBill")}
          fileName={bill.number}
          fetchLink={() => shopInvoicesPdf(bill.id)}
        />
      </Card>
      <Section title={t("items")}>
        <View style={[styles.list, { borderColor: colors.border, borderRadius: radius + 4 }]}>
          {bill.lines.map((line, index) => (
            <View
              key={line.id}
              style={[
                styles.line,
                index > 0 && { borderTopWidth: 1, borderTopColor: colors.border },
              ]}
            >
              <View style={styles.flex}>
                <Text size="sm" weight="medium">
                  {line.description}
                </Text>
                {line.is_free ? <FreeLineLabel scheme={line.scheme_name} /> : null}
                <Text size="sm" tone="muted">
                  {`${formatQty(line.quantity)} ${line.unit_code} × `}
                  <MoneyText value={line.unit_price} size="sm" tone="muted" />
                  {line.credited_quantity !== "0.000"
                    ? ` · ${t("returned", { qty: formatQty(line.credited_quantity) })}`
                    : ""}
                </Text>
              </View>
              <MoneyText value={line.line_total} size="sm" weight="medium" />
            </View>
          ))}
        </View>
        {canReturn ? (
          <Button
            variant="outline"
            label={tr("open")}
            icon={<Feather name="rotate-ccw" size={16} color={colors.foreground} />}
            onPress={() =>
              router.push({ pathname: "/shop/invoices/[id]/return", params: { id: bill.id } })
            }
          />
        ) : null}
      </Section>
      <BillReturns bill={bill} />
      <Card>
        <Row label={t("total")}>
          <MoneyText value={bill.grand_total} size="sm" weight="semibold" />
        </Row>
        <Row label={t("paid")}>
          <MoneyText value={bill.amount_paid} size="sm" />
        </Row>
        {bill.amount_credited !== "0.00" ? (
          <Row label={t("credited")}>
            <MoneyText value={bill.amount_credited} size="sm" />
          </Row>
        ) : null}
      </Card>
      {bill.credit_notes.length ? (
        <Section title={t("creditNotes")}>
          {bill.credit_notes.map((note) => (
            <Card key={note.id}>
              <Text weight="medium">{note.number}</Text>
              <Text tone="muted" size="sm">
                <DateText value={note.note_date} size="sm" tone="muted" />
                {" · "}
                <MoneyText value={note.grand_total} size="sm" tone="muted" />
              </Text>
              <DocumentButton
                label={t("download")}
                fileName={note.number}
                fetchLink={() => shopCreditNotesPdf(note.id)}
              />
            </Card>
          ))}
        </Section>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  head: { gap: space[1] },
  wrap: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space[2] },
  section: { gap: space[2] },
  between: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: space[3],
  },
  notice: { padding: space[3] },
  list: { borderWidth: 1 },
  line: { padding: space[3], flexDirection: "row", gap: space[3] },
});
