"use client";

import { CheckCircle2, Loader2, Smartphone } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useHostBranding } from "@/components/auth/tenant-branding";
import { PageSkeleton } from "@/components/shared/skeletons";
import { ProviderMessage } from "@/components/shared/provider-message";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/errors";
import {
  payCheckoutOutcome,
  paySession,
  usePayCheckout,
} from "@/lib/api/generated/endpoints/pay/pay";
import type { PayCheckout } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatMoney } from "@/lib/format";
import { useTranslations } from "@/lib/i18n/translations";

import { PayNow } from "./pay";

const OPEN = new Set(["CREATED", "ATTEMPTED"]);
const storageKey = (intentId: string) => `pay:${intentId}`;

function readToken(intentId: string): string | null {
  try {
    return sessionStorage.getItem(storageKey(intentId));
  } catch {
    return null;
  }
}

function keepToken(intentId: string, token: string) {
  try {
    sessionStorage.setItem(storageKey(intentId), token); // this tab only: back from a UPI app
  } catch {
    // Without storage the page still works until the tab reloads.
  }
}

/** The session: from the link's one-time code (removed from the address bar at once), or the one
 * this tab already has after coming back from the gateway's page or a UPI app. */
function usePaySession(intentId: string) {
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const code = new URLSearchParams(window.location.hash.slice(1)).get("code");
    window.history.replaceState(null, "", window.location.pathname);
    const kept = readToken(intentId);
    const open = async (): Promise<string> => {
      if (!code) {
        if (kept) return kept;
        throw new ApiError(401, { code: "PAY_PAGE_CLOSED", message: "", details: {} });
      }
      try {
        const token = (await paySession({ code })).data.token;
        keepToken(intentId, token);
        return token;
      } catch (err) {
        if (kept) return kept; // a reload that still had the used code in its address
        throw err;
      }
    };
    open().then(setToken, setError);
  }, [intentId]);
  return { token, error };
}

function BackToApp({ checkout, variant }: { checkout?: PayCheckout; variant?: "outline" }) {
  const t = useTranslations("shop.pay");
  if (!checkout) return null;
  return (
    <Button asChild variant={variant} className="min-h-11 w-full gap-2">
      <a href={checkout.app_return_url}>
        <Smartphone aria-hidden className="size-4" />
        {t("backToApp")}
      </a>
    </Button>
  );
}

/** The Android app's payment page (ADR-061 item 9): the app opens it in a Chrome Custom Tab so
 * UPI apps can open, for this one checkout only. No shop menus and no shop session; back in the
 * app, the app asks the server whether it was paid. */
export function BrowserPayPage({ intentId }: { intentId: string }) {
  const t = useTranslations("shop.pay");
  const tp = useTranslations("providerMessages");
  const errors = useErrorText();
  const session = usePaySession(intentId);
  const auth = { headers: { Authorization: `Pay ${session.token ?? ""}` } };
  const query = usePayCheckout({
    request: auth,
    query: {
      enabled: session.token !== null,
      retry: false,
      refetchInterval: (q) =>
        q.state.data?.data.page_open && OPEN.has(q.state.data.data.status) ? 3000 : false,
    },
  });
  const checkout = query.data?.data;
  const paid = checkout?.status === "PAID";
  useEffect(() => {
    // Paid: back to the app, which reads the payment from the server.
    if (!paid || !checkout) return;
    const timer = setTimeout(() => window.location.assign(checkout.app_return_url), 1500);
    return () => clearTimeout(timer);
  }, [paid, checkout]);

  const failure = session.error ?? query.error;
  if (failure) {
    return (
      <PayFrame>
        <p role="alert" className="text-muted-foreground">
          {errors.message(failure)}
        </p>
      </PayFrame>
    );
  }
  if (!checkout) return <PageSkeleton />;
  return (
    <PayFrame>
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{formatMoney(checkout.amount)}</h1>
        <p className="text-muted-foreground">
          {checkout.invoice_id
            ? t("forBill", { number: checkout.invoice_number })
            : t(`purposes.${checkout.purpose}`)}
        </p>
      </div>
      {paid ? (
        <section role="status" className="bg-success/10 space-y-3 rounded-xl p-4">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <CheckCircle2 aria-hidden className="text-success-strong size-6" />
            {t("paid")}
          </h2>
          <p className="text-sm">{t("paidBody", { receipt: checkout.receipt_number })}</p>
          <BackToApp checkout={checkout} />
        </section>
      ) : !checkout.page_open || checkout.status === "EXPIRED" ? (
        <section className="space-y-3 rounded-xl border p-4">
          <p>{t("expired")}</p>
          <BackToApp checkout={checkout} />
        </section>
      ) : (
        <section className="space-y-3">
          {checkout.awaiting_confirmation ? (
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
              <ProviderMessage line={tp("payment")} message={checkout.last_error} />
            </p>
          ) : null}
          <PayNow
            checkout={checkout}
            onOutcome={() => void query.refetch()}
            noteOutcome={(outcome) => payCheckoutOutcome({ outcome }, auth)}
            returnTo="pay"
          />
          <p className="text-muted-foreground text-sm">{t("safe")}</p>
          <BackToApp checkout={checkout} variant="outline" />
        </section>
      )}
    </PayFrame>
  );
}

/** Whose payment this is: the distributor's logo and name, as on its own sign-in page. */
function PayFrame({ children }: { children: ReactNode }) {
  const { branding } = useHostBranding();
  return (
    <main className="mx-auto max-w-md space-y-5 px-4 py-6">
      {branding ? (
        <div className="flex items-center gap-3 border-b pb-4">
          {branding.logo_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- tenant logo from storage
            <img src={branding.logo_url} alt="" className="size-10 rounded-lg object-contain" />
          ) : null}
          <span className="text-lg font-semibold">{branding.display_name}</span>
        </div>
      ) : null}
      {children}
    </main>
  );
}
