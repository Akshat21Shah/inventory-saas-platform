"use client";

import {
  ArrowLeft,
  Bell,
  ChevronRight,
  FileText,
  LogOut,
  ReceiptText,
  ScrollText,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { DocumentButton } from "@/components/billing/document-button";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { CardSkeleton, PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FreeLineLabel } from "./free-goods";
import {
  shopCreditNotesPdf,
  shopInvoicesPdf,
  shopPaymentsReceipt,
  useShopAccount,
  useShopHome,
  useShopInvoicesList,
  useShopInvoicesRetrieve,
  useShopLedger,
  useShopPaymentsList,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { ShopInvoicesListState } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { formatDate, formatMoney, formatQty } from "@/lib/format";
import { useTranslations } from "@/lib/i18n/translations";
import { cn } from "@/lib/utils";

import { PayAccountCard, PayBillButton } from "./pay";
import { BillReturns, ReturnItemsButton } from "./returns";

function Pager({ pager }: { pager: ReturnType<ReturnType<typeof useCursor>["pagination"]> }) {
  const t = useTranslations("shop.money");
  if (!pager) return null;
  return (
    <div className="flex justify-between">
      <Button
        variant="outline"
        className="min-h-11"
        disabled={!pager.hasPrevious}
        onClick={pager.onPrevious}
      >
        {t("newer")}
      </Button>
      <Button
        variant="outline"
        className="min-h-11"
        disabled={!pager.hasNext}
        onClick={pager.onNext}
      >
        {t("older")}
      </Button>
    </div>
  );
}

function Back({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="text-muted-foreground inline-flex min-h-11 items-center gap-1 text-sm hover:underline"
    >
      <ArrowLeft aria-hidden className="size-4" />
      {label}
    </Link>
  );
}

/** "You owe ₹X" on the shop's home page, when it owes anything. */
export function OwedCard() {
  const t = useTranslations("shop.money");
  const owed = useShopHome().data?.data.outstanding;
  if (!owed || owed.balance === "0.00") return null;
  const credit = owed.balance.startsWith("-");
  return (
    <Link
      href="/shop/account"
      className={cn(
        "flex min-h-14 items-center justify-between gap-3 rounded-xl border p-4",
        owed.overdue !== "0.00" ? "border-destructive/40 bg-destructive/5" : "bg-muted/40",
      )}
    >
      <span>
        <span className="block text-sm">{credit ? t("inCredit") : t("youOwe")}</span>
        <span className="text-lg font-semibold">
          {formatMoney(credit ? owed.balance.slice(1) : owed.balance)}
        </span>
        {owed.overdue !== "0.00" ? (
          <span className="text-destructive block text-sm">
            {t("overdue", { amount: formatMoney(owed.overdue) })}
          </span>
        ) : null}
      </span>
      <ChevronRight aria-hidden className="text-muted-foreground size-5" />
    </Link>
  );
}

/** The shop's account: what it owes, how old, its credit, and the money pages. */
export function ShopAccountPage() {
  const t = useTranslations("shop.money");
  const accountT = useTranslations("account");
  const { signOut } = useAuth();
  const query = useShopAccount();
  const account = query.data?.data;
  const menu = [
    { href: "/shop/invoices", label: t("bills"), icon: FileText },
    { href: "/shop/statement", label: t("statement"), icon: ScrollText },
    { href: "/shop/payments", label: t("payments"), icon: ReceiptText },
    { href: "/shop/account/messages", label: t("messages"), icon: Bell },
    { href: "/shop/account/security", label: t("profile"), icon: UserRound },
  ];
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : account ? (
        <section className="space-y-3 rounded-xl border p-4" aria-labelledby="owe-heading">
          <h2 id="owe-heading" className="sr-only">
            {t("summary")}
          </h2>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-muted-foreground">{t("youOwe")}</dt>
              <dd className="text-xl font-semibold">
                <MoneyText value={account.position.owed} />
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("overdueLabel")}</dt>
              <dd
                className={cn(
                  "text-xl font-semibold",
                  account.position.overdue !== "0.00" && "text-destructive",
                )}
              >
                <MoneyText value={account.position.overdue} />
              </dd>
            </div>
            {account.position.unapplied_credit !== "0.00" ? (
              <div>
                <dt className="text-muted-foreground">{t("creditWithUs")}</dt>
                <dd className="font-semibold">
                  <MoneyText value={account.position.unapplied_credit} />
                </dd>
              </div>
            ) : null}
            {account.available_credit !== null ? (
              <div>
                <dt className="text-muted-foreground">{t("canOrder")}</dt>
                <dd className="font-semibold">
                  <MoneyText value={account.available_credit} />
                </dd>
              </div>
            ) : null}
          </dl>
          <PayAccountCard owed={account.position.owed} online={account.online_payments} />
          {account.orders_blocked_for_overdue ? (
            <p className="bg-destructive/10 rounded-xl p-3 text-sm">{t("blocked")}</p>
          ) : account.overdue_bills ? (
            <p className="bg-warning/15 rounded-xl p-3 text-sm">
              {t("overdueBills", { count: account.overdue_bills })}
            </p>
          ) : null}
        </section>
      ) : null}
      <nav aria-label={t("menu")}>
        <ul className="divide-y rounded-xl border">
          {menu.map((item) => (
            <li key={item.href}>
              <Link href={item.href} className="flex min-h-14 items-center gap-3 px-4">
                <item.icon aria-hidden className="text-muted-foreground size-5" />
                <span className="flex-1 font-medium">{item.label}</span>
                <ChevronRight aria-hidden className="text-muted-foreground size-5" />
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <Button
        variant="outline"
        className="min-h-11 w-full sm:w-auto"
        onClick={() => void signOut()}
      >
        <LogOut aria-hidden />
        {accountT("signOut")}
      </Button>
    </div>
  );
}

const STATES: ShopInvoicesListState[] = ["unpaid", "overdue", "paid"];

export function ShopBillsPage() {
  const t = useTranslations("shop.money");
  const [state, setState] = useState<ShopInvoicesListState>("unpaid");
  const cursor = useCursor();
  const query = useShopInvoicesList({ state, cursor: cursor.cursor });
  const page = query.data?.data;
  const rows = page?.results ?? [];
  return (
    <div className="space-y-4">
      <Back href="/shop/account" label={t("title")} />
      <h1 className="text-2xl font-semibold">{t("bills")}</h1>
      <div role="tablist" aria-label={t("bills")} className="-mx-4 flex gap-2 overflow-x-auto px-4">
        {STATES.map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={state === value}
            onClick={() => {
              setState(value);
              cursor.reset();
            }}
            className={cn(
              "flex min-h-11 shrink-0 items-center rounded-full border px-4 text-sm",
              state === value ? "border-brand-200 bg-brand-50 font-medium" : "hover:bg-muted",
            )}
          >
            {t(`state.${value}`)}
          </button>
        ))}
      </div>
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title={t(`noBills.${state}`)} />
      ) : (
        <ul className="divide-y rounded-xl border">
          {rows.map((bill) => (
            <li key={bill.id}>
              <Link
                href={`/shop/invoices/${bill.id}`}
                className="flex min-h-16 items-center justify-between gap-3 p-4"
              >
                <span className="min-w-0">
                  <span className="block font-medium">{bill.number}</span>
                  <span className="text-muted-foreground text-sm">
                    {formatDate(bill.invoice_date)}
                    {bill.days_overdue > 0 ? (
                      <span className="text-destructive">
                        {" · "}
                        {t("daysLate", { days: bill.days_overdue })}
                      </span>
                    ) : bill.balance_due !== "0.00" ? (
                      ` · ${t("dueOn", { date: formatDate(bill.due_date) })}`
                    ) : null}
                  </span>
                </span>
                <span className="text-right">
                  <MoneyText
                    value={bill.balance_due !== "0.00" ? bill.balance_due : bill.grand_total}
                    className="block font-semibold"
                  />
                  <StatusBadge status={bill.payment_status} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Pager pager={cursor.pagination(page)} />
    </div>
  );
}

export function ShopBillPage({ invoiceId }: { invoiceId: string }) {
  const t = useTranslations("shop.money");
  const query = useShopInvoicesRetrieve(invoiceId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const bill = query.data?.data;
  if (!bill) return <EmptyState title={t("notFound")} />;
  return (
    <div className="space-y-5">
      <Back href="/shop/invoices" label={t("bills")} />
      <div className="space-y-1">
        <h1 className="flex flex-wrap items-center gap-2 text-2xl font-semibold">
          {t("billHeading", { number: bill.number })}
          <StatusBadge status={bill.status === "CANCELLED" ? "CANCELLED" : bill.payment_status} />
        </h1>
        <p className="text-muted-foreground text-sm">
          {formatDate(bill.invoice_date)} · {t("forOrder", { number: bill.order.number })}
        </p>
      </div>
      <section className="space-y-2 rounded-xl border p-4">
        <div className="flex justify-between text-lg font-semibold">
          <span>{t("stillToPay")}</span>
          <MoneyText value={bill.balance_due} />
        </div>
        {bill.balance_due !== "0.00" ? (
          <p className={cn("text-sm", bill.days_overdue > 0 && "text-destructive")}>
            {bill.days_overdue > 0
              ? t("daysLate", { days: bill.days_overdue })
              : t("dueOn", { date: formatDate(bill.due_date) })}
          </p>
        ) : null}
        {bill.status === "CANCELLED" ? (
          <p className="bg-muted rounded-xl p-3 text-sm">{t("billCancelled")}</p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {bill.status === "ISSUED" ? (
            <PayBillButton invoiceId={bill.id} balance={bill.balance_due} />
          ) : null}
          <DocumentButton fetchLink={() => shopInvoicesPdf(bill.id)} variant="default">
            {t("downloadBill")}
          </DocumentButton>
        </div>
      </section>
      <section className="space-y-2" aria-labelledby="bill-items">
        <h2 id="bill-items" className="font-semibold">
          {t("items")}
        </h2>
        <ul className="divide-y rounded-xl border">
          {bill.lines.map((line) => (
            <li key={line.id} className="flex justify-between gap-3 p-3 text-sm">
              <span className="min-w-0">
                <span className="block font-medium">{line.description}</span>
                {line.is_free ? <FreeLineLabel scheme={line.scheme_name} /> : null}
                <span className="text-muted-foreground block">
                  {formatQty(line.quantity)} {line.unit_code} ×{" "}
                  <MoneyText value={line.unit_price} />
                  {line.credited_quantity !== "0.000"
                    ? ` · ${t("returned", { qty: formatQty(line.credited_quantity) })}`
                    : ""}
                </span>
              </span>
              <MoneyText value={line.line_total} className="font-medium" />
            </li>
          ))}
        </ul>
        <ReturnItemsButton bill={bill} />
      </section>
      <BillReturns bill={bill} />
      <dl className="space-y-1 rounded-xl border p-4 text-sm">
        <div className="flex justify-between">
          <dt>{t("total")}</dt>
          <dd className="font-semibold">
            <MoneyText value={bill.grand_total} />
          </dd>
        </div>
        <div className="flex justify-between">
          <dt>{t("paid")}</dt>
          <dd>
            <MoneyText value={bill.amount_paid} />
          </dd>
        </div>
        {bill.amount_credited !== "0.00" ? (
          <div className="flex justify-between">
            <dt>{t("credited")}</dt>
            <dd>
              <MoneyText value={bill.amount_credited} />
            </dd>
          </div>
        ) : null}
      </dl>
      {bill.credit_notes.length ? (
        <section className="space-y-2" aria-labelledby="bill-credits">
          <h2 id="bill-credits" className="font-semibold">
            {t("creditNotes")}
          </h2>
          <ul className="divide-y rounded-xl border">
            {bill.credit_notes.map((note) => (
              <li
                key={note.id}
                className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm"
              >
                <span>
                  <span className="block font-medium">{note.number}</span>
                  <span className="text-muted-foreground">
                    {formatDate(note.note_date)} · <MoneyText value={note.grand_total} />
                  </span>
                </span>
                <DocumentButton fetchLink={() => shopCreditNotesPdf(note.id)}>
                  {t("download")}
                </DocumentButton>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

export function ShopStatementPage() {
  const t = useTranslations("shop.money");
  const entries = useTranslations("billing.entryTypes");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const query = useShopLedger({ date_from: from || undefined, date_to: to || undefined });
  const statement = query.data?.data;
  return (
    <div className="space-y-4">
      <Back href="/shop/account" label={t("title")} />
      <h1 className="text-2xl font-semibold">{t("statement")}</h1>
      <p className="text-muted-foreground text-sm">{t("statementBody")}</p>
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : statement ? (
        <>
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1 text-sm">
              {t("from")}
              <Input
                type="date"
                className="min-h-11"
                value={from || statement.date_from}
                onChange={(e) => setFrom(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              {t("to")}
              <Input
                type="date"
                className="min-h-11"
                value={to || statement.date_to}
                onChange={(e) => setTo(e.target.value)}
              />
            </label>
          </div>
          <div className="flex justify-between rounded-xl border px-4 py-3 text-sm">
            <span>{t("balanceOn", { date: formatDate(statement.date_from) })}</span>
            <MoneyText value={statement.opening_balance} className="font-medium" />
          </div>
          {statement.lines.length === 0 ? (
            <EmptyState title={t("noEntries")} />
          ) : (
            <ul className="divide-y rounded-xl border text-sm">
              {statement.lines.map((line) => (
                <li key={line.id} className="space-y-0.5 p-3">
                  <div className="flex justify-between gap-3">
                    <span className="font-medium">
                      {entries(line.entry_type)} {line.reference_number}
                    </span>
                    {line.debit !== "0.00" ? (
                      <MoneyText value={line.debit} />
                    ) : (
                      <span className="text-success-strong">
                        −<MoneyText value={line.credit} />
                      </span>
                    )}
                  </div>
                  <div className="text-muted-foreground flex justify-between gap-3 text-xs">
                    <span>
                      <DateText value={line.entry_date} />
                    </span>
                    <span>
                      {t("balance")} <MoneyText value={line.balance} />
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div className="flex justify-between rounded-xl border px-4 py-3 text-sm font-semibold">
            <span>{t("balanceOn", { date: formatDate(statement.date_to) })}</span>
            <MoneyText value={statement.closing_balance} />
          </div>
        </>
      ) : null}
    </div>
  );
}

export function ShopPaymentsPage() {
  const t = useTranslations("shop.money");
  const modes = useTranslations("billing.modes");
  const cursor = useCursor();
  const query = useShopPaymentsList({ cursor: cursor.cursor });
  const page = query.data?.data;
  const rows = page?.results ?? [];
  return (
    <div className="space-y-4">
      <Back href="/shop/account" label={t("title")} />
      <h1 className="text-2xl font-semibold">{t("payments")}</h1>
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title={t("noPayments")} />
      ) : (
        <ul className="divide-y rounded-xl border">
          {rows.map((payment) => (
            <li key={payment.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
              <span className="min-w-0">
                <span className="block font-semibold">
                  <MoneyText value={payment.amount} />
                </span>
                <span className="text-muted-foreground text-sm">
                  {formatDate(payment.payment_date)} · {modes(payment.mode)}
                  {payment.collected_by_name
                    ? ` · ${t("collectedBy", { name: payment.collected_by_name })}`
                    : ""}
                </span>
                {payment.status === "BOUNCED" || payment.status === "REVERSED" ? (
                  <span className="text-destructive block text-sm">
                    {t(`status.${payment.status}`)}
                  </span>
                ) : payment.status === "PENDING_CLEARANCE" ? (
                  <span className="text-warning-strong block text-sm">
                    {t("status.PENDING_CLEARANCE")}
                  </span>
                ) : null}
              </span>
              <DocumentButton fetchLink={() => shopPaymentsReceipt(payment.id)}>
                {t("receipt")}
              </DocumentButton>
            </li>
          ))}
        </ul>
      )}
      <Pager pager={cursor.pagination(page)} />
    </div>
  );
}
