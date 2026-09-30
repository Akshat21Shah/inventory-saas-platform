"use client";

import { ArrowLeft, CheckCircle2, CreditCard, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { DocumentButton } from "@/components/billing/document-button";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { PageSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  shopCheckoutOutcome,
  shopCheckoutStart,
  shopPaymentsReceipt,
  useShopAccount,
  useShopCheckout,
} from "@/lib/api/generated/endpoints/shop/shop";
import type {
  Checkout,
  CheckoutInputRequest,
  CheckoutOutcomeOutcomeEnum,
} from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatMoney } from "@/lib/format";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";

/** Starts (or re-opens) a checkout and goes to its page. The server keeps one active checkout
 * per bill or purpose, so a second tap opens the same one; each tap has its own key. */
function useStartCheckout() {
  const router = useRouter();
  const { message } = useErrorText();
  const [busy, setBusy] = useState(false);
  async function start(body: CheckoutInputRequest) {
    setBusy(true);
    try {
      const response = await shopCheckoutStart(body, idempotent(newIdempotencyKey()));
      router.push(`/shop/payments/checkout/${response.data.id}`);
    } catch (err) {
      toast.error(message(err)); // e.g. "Payment service is busy, please try again in a minute."
      setBusy(false);
    }
  }
  return { start, busy };
}

/** "Pay ₹X" on a bill, while the distributor takes online payments. */
export function PayBillButton({ invoiceId, balance }: { invoiceId: string; balance: string }) {
  const t = useTranslations("shop.pay");
  const online = useShopAccount().data?.data.online_payments;
  const { start, busy } = useStartCheckout();
  if (!online || balance === "0.00") return null;
  return (
    <Button
      className="min-h-11 w-full gap-2 sm:w-auto"
      disabled={busy}
      onClick={() => void start({ purpose: "INVOICE", invoice_id: invoiceId })}
    >
      <CreditCard aria-hidden className="size-4" />
      {t("payBill", { amount: formatMoney(balance) })}
    </Button>
  );
}

/** On the account page: pay everything owed, or an amount the shop chooses. */
export function PayAccountCard({ owed, online }: { owed: string; online: boolean }) {
  const t = useTranslations("shop.pay");
  const { start, busy } = useStartCheckout();
  const [amount, setAmount] = useState("");
  if (!online) return null;
  const owes = !owed.startsWith("-") && owed !== "0.00";

  function other(event: FormEvent) {
    event.preventDefault();
    if (amount.trim()) void start({ purpose: "CUSTOM", amount: amount.trim() });
  }

  return (
    <section className="space-y-3 rounded-xl border p-4" aria-labelledby="pay-heading">
      <h2 id="pay-heading" className="font-semibold">
        {t("title")}
      </h2>
      {owes ? (
        <Button
          className="min-h-11 w-full gap-2"
          disabled={busy}
          onClick={() => void start({ purpose: "OUTSTANDING" })}
        >
          <CreditCard aria-hidden className="size-4" />
          {t("payAll", { amount: formatMoney(owed) })}
        </Button>
      ) : null}
      <form onSubmit={other} className="flex flex-wrap items-end gap-2" noValidate>
        <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm">
          {t("otherAmount")}
          <Input
            type="number"
            inputMode="decimal"
            min="1"
            step="0.01"
            className="h-11"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </label>
        <Button type="submit" variant="outline" className="min-h-11" disabled={busy || !amount}>
          {t("payAmount")}
        </Button>
      </form>
    </section>
  );
}

interface RazorpayOptions {
  key: string;
  order_id: string;
  amount: number;
  currency: string;
  name: string;
  description: string;
  prefill?: Record<string, string>;
  handler: () => void;
  modal: { ondismiss: () => void };
}
interface RazorpayInstance {
  open: () => void;
  on: (event: string, callback: () => void) => void;
}
declare global {
  interface Window {
    Razorpay?: new (options: RazorpayOptions) => RazorpayInstance;
  }
}

// TODO(verify): Razorpay Standard Checkout's script URL and option names against the official
// docs before going live (pre-production item 25). The server gives the options; no secrets.
const RAZORPAY_SCRIPT = "https://checkout.razorpay.com/v1/checkout.js";

function loadRazorpay(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = RAZORPAY_SCRIPT;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("checkout script"));
    document.body.appendChild(script);
  });
}

type Options = {
  provider?: string;
  checkout_url?: string;
} & Omit<RazorpayOptions, "handler" | "modal">;

/** Opens the gateway: the test gateway's page in dev, Razorpay's checkout otherwise. What the
 * page sees is only noted; the payment counts once the gateway's signed webhook confirms it. */
function PayNow({ checkout, onOutcome }: { checkout: Checkout; onOutcome: () => void }) {
  const t = useTranslations("shop.pay");
  const [busy, setBusy] = useState(false);
  const options = (checkout.checkout ?? {}) as Options;

  async function note(outcome: CheckoutOutcomeOutcomeEnum) {
    try {
      await shopCheckoutOutcome(checkout.id, { outcome });
    } finally {
      onOutcome();
    }
  }

  async function open() {
    if (options.checkout_url) {
      window.location.assign(options.checkout_url);
      return;
    }
    setBusy(true);
    try {
      await loadRazorpay();
      if (!window.Razorpay) throw new Error("checkout script");
      const gateway = new window.Razorpay({
        key: options.key,
        order_id: options.order_id,
        amount: options.amount,
        currency: options.currency,
        name: options.name,
        description: options.description,
        prefill: options.prefill,
        handler: () => void note("success"),
        modal: { ondismiss: () => void note("dismissed") },
      });
      gateway.on("payment.failed", () => void note("failed"));
      gateway.open();
    } catch {
      toast.error(t("couldNotOpen"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button className="min-h-12 w-full gap-2 text-base" disabled={busy} onClick={() => void open()}>
      <CreditCard aria-hidden className="size-5" />
      {t("payNow", { amount: formatMoney(checkout.amount) })}
    </Button>
  );
}

const OPEN = new Set(["CREATED", "ATTEMPTED"]);

/** One checkout: pay, then wait here until the gateway confirms (the page follows it). */
export function ShopCheckoutPage({ intentId }: { intentId: string }) {
  const t = useTranslations("shop.pay");
  const query = useShopCheckout(intentId, {
    query: {
      refetchInterval: (q) => (OPEN.has(q.state.data?.data.status ?? "") ? 3000 : false),
    },
  });
  if (query.isLoading) return <PageSkeleton />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const checkout = query.data?.data;
  if (!checkout) return <EmptyState title={t("notFound")} />;
  const back = checkout.invoice_id ? `/shop/invoices/${checkout.invoice_id}` : "/shop/account";
  const tried = checkout.status === "ATTEMPTED";
  return (
    <div className="mx-auto max-w-md space-y-5">
      <Link
        href={back}
        className="text-muted-foreground inline-flex min-h-11 items-center gap-1 text-sm hover:underline"
      >
        <ArrowLeft aria-hidden className="size-4" />
        {checkout.invoice_id ? t("backToBill") : t("backToAccount")}
      </Link>
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{formatMoney(checkout.amount)}</h1>
        <p className="text-muted-foreground">
          {checkout.invoice_id
            ? t("forBill", { number: checkout.invoice_number })
            : t(`purposes.${checkout.purpose}`)}
        </p>
      </div>
      {checkout.status === "PAID" ? (
        <section
          role="status"
          className="bg-success/10 space-y-3 rounded-xl p-4"
          aria-labelledby="paid-heading"
        >
          <h2 id="paid-heading" className="flex items-center gap-2 text-lg font-semibold">
            <CheckCircle2 aria-hidden className="text-success-strong size-6" />
            {t("paid")}
          </h2>
          <p className="text-sm">{t("paidBody", { receipt: checkout.receipt_number })}</p>
          {checkout.payment_id ? (
            <DocumentButton
              fetchLink={() => shopPaymentsReceipt(checkout.payment_id ?? "")}
              variant="default"
            >
              {t("receipt")}
            </DocumentButton>
          ) : null}
        </section>
      ) : checkout.status === "EXPIRED" ? (
        <section className="space-y-3 rounded-xl border p-4">
          <p>{t("expired")}</p>
          <Button asChild className="min-h-11">
            <Link href={back}>{t("startAgain")}</Link>
          </Button>
        </section>
      ) : (
        <section className="space-y-3">
          {tried ? (
            <p
              className="bg-muted flex items-center gap-2 rounded-xl p-3 text-sm"
              aria-live="polite"
            >
              <Loader2 aria-hidden className="size-4 shrink-0 motion-safe:animate-spin" />
              {t("waiting")}
            </p>
          ) : null}
          {checkout.last_error ? (
            <p role="alert" className="bg-destructive/10 rounded-xl p-3 text-sm">
              {t("lastError", { error: checkout.last_error })}
            </p>
          ) : null}
          <PayNow checkout={checkout} onOutcome={() => void query.refetch()} />
          <p className="text-muted-foreground text-sm">{t("safe")}</p>
        </section>
      )}
    </div>
  );
}
