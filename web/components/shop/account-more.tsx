"use client";

/**
 * More of the shop's account (owner, Phase 11b checkpoint review item 5, kept the same in the
 * Android app): every return asked for, the delivery addresses, help from the distributor, and
 * privacy and data.
 */
import {
  ArrowLeft,
  ChevronRight,
  ExternalLink,
  LifeBuoy,
  Mail,
  MessageCircle,
  Phone,
  Undo2,
} from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { DateText } from "@/components/shared/money-text";
import { CardSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { useAppConfig } from "@/lib/api/generated/endpoints/public/public";
import {
  useShopAddressesList,
  useShopDistributor,
  useShopReturnRequestsList,
} from "@/lib/api/generated/endpoints/shop/shop";
import { useCursor } from "@/lib/api/pagination";
import { formatQty } from "@/lib/format";
import { useTranslations } from "@/lib/i18n/translations";

function Back() {
  const t = useTranslations("shop.money");
  return (
    <Link
      href="/shop/account"
      className="text-muted-foreground inline-flex min-h-11 items-center gap-1 text-sm hover:underline"
    >
      <ArrowLeft aria-hidden className="size-4" />
      {t("title")}
    </Link>
  );
}

/** Every return the shop asked for, newest first, each opening its bill (withdraw it there). */
export function ShopReturnsPage() {
  const t = useTranslations("shop.returns");
  const money = useTranslations("shop.money");
  const cursor = useCursor();
  const query = useShopReturnRequestsList({ cursor: cursor.cursor });
  const page = query.data?.data;
  const rows = page?.results ?? [];
  const pager = cursor.pagination(page);
  return (
    <div className="space-y-4">
      <Back />
      <h1 className="text-2xl font-semibold">{t("heading")}</h1>
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState icon={Undo2} title={t("none")} description={t("noneBody")} />
      ) : (
        <ul className="divide-y rounded-xl border">
          {rows.map((request) => (
            <li key={request.id}>
              <Link
                href={`/shop/invoices/${request.invoice.id}`}
                className="flex min-h-16 items-center gap-3 p-4"
              >
                <span className="min-w-0 flex-1 space-y-1">
                  <span className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{request.number}</span>
                    <StatusBadge status={request.status} labels="shopReturnStatus" />
                  </span>
                  <span className="text-muted-foreground block text-sm">
                    <DateText value={request.created_at} /> ·{" "}
                    {money("billHeading", { number: request.invoice.number })}
                  </span>
                  <span className="text-muted-foreground block text-sm">
                    {request.lines
                      .map((line) => `${formatQty(line.quantity)} ${line.description}`)
                      .join(", ")}
                  </span>
                  {request.status === "REJECTED" && request.decision_note ? (
                    <span className="block text-sm">
                      {t("why", { reason: request.decision_note })}
                    </span>
                  ) : null}
                  {request.credit_note ? (
                    <span className="block text-sm">
                      {t("credited", { number: request.credit_note.number })}
                    </span>
                  ) : null}
                </span>
                <ChevronRight aria-hidden className="text-muted-foreground size-5 shrink-0" />
              </Link>
            </li>
          ))}
        </ul>
      )}
      {pager ? (
        <div className="flex justify-between">
          <Button
            variant="outline"
            className="min-h-11"
            disabled={!pager.hasPrevious}
            onClick={pager.onPrevious}
          >
            {money("newer")}
          </Button>
          <Button
            variant="outline"
            className="min-h-11"
            disabled={!pager.hasNext}
            onClick={pager.onNext}
          >
            {money("older")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** The delivery addresses, to see; the distributor adds and changes them. */
export function ShopAddressesPage() {
  const t = useTranslations("shop.account.addresses");
  const query = useShopAddressesList();
  const list = query.data?.data ?? [];
  return (
    <div className="space-y-4">
      <Back />
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="text-muted-foreground text-sm">{t("body")}</p>
      </div>
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : list.length === 0 ? (
        <EmptyState title={t("none")} />
      ) : (
        <ul className="space-y-3">
          {list.map((address) => (
            <li key={address.id} className="space-y-1 rounded-xl border p-4">
              <p className="flex flex-wrap items-center gap-2 font-medium">
                {address.name}
                {address.is_default ? (
                  <span className="bg-brand-100 text-brand-800 rounded-full px-2 py-0.5 text-xs font-medium">
                    {t("default")}
                  </span>
                ) : null}
              </p>
              <p className="text-sm">{[address.line1, address.line2].filter(Boolean).join(", ")}</p>
              <p className="text-muted-foreground text-sm">
                {[address.city, address.state, address.pincode].filter(Boolean).join(", ")}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A phone number as WhatsApp's link wants it: digits only, with India's 91. */
function whatsappNumber(phone: string): string {
  const digits = phone.replace(/\D/g, "");
  return digits.length === 10 ? `91${digits}` : digits;
}

/** Help: the distributor's phone and email, to call, write on WhatsApp or email. */
export function ShopHelpPage() {
  const t = useTranslations("shop.account.help");
  const query = useShopDistributor();
  const distributor = query.data?.data;
  return (
    <div className="space-y-4">
      <Back />
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="text-muted-foreground text-sm">{t("body")}</p>
      </div>
      {query.isLoading ? (
        <CardSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : distributor ? (
        <section className="space-y-3 rounded-xl border p-4">
          <h2 className="text-lg font-semibold">{distributor.name}</h2>
          {distributor.phone ? (
            <>
              <p className="text-muted-foreground text-sm">{distributor.phone}</p>
              <div className="flex flex-wrap gap-2">
                <Button asChild className="min-h-11">
                  <a href={`tel:${distributor.phone}`}>
                    <Phone aria-hidden />
                    {t("call")}
                  </a>
                </Button>
                <Button asChild variant="outline" className="min-h-11">
                  <a
                    href={`https://wa.me/${whatsappNumber(distributor.phone)}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <MessageCircle aria-hidden />
                    {t("whatsapp")}
                  </a>
                </Button>
              </div>
            </>
          ) : null}
          {distributor.email ? (
            <>
              <p className="text-muted-foreground text-sm">{distributor.email}</p>
              <Button asChild variant="outline" className="min-h-11">
                <a href={`mailto:${distributor.email}`}>
                  <Mail aria-hidden />
                  {t("email")}
                </a>
              </Button>
            </>
          ) : null}
          {!distributor.phone && !distributor.email ? (
            <p className="text-muted-foreground text-sm">{t("noContact")}</p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

/** Privacy and data: the privacy policy, and asking the distributor to delete the shop's data. */
export function ShopPrivacyPage() {
  const t = useTranslations("shop.account.privacy");
  const policy = useAppConfig().data?.data.privacy_policy_url ?? "";
  return (
    <div className="space-y-4">
      <Back />
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <section className="space-y-2 rounded-xl border p-4">
        <h2 className="font-semibold">{t("policyTitle")}</h2>
        {policy ? (
          <Button asChild variant="outline" className="min-h-11">
            <a href={policy} target="_blank" rel="noreferrer">
              <ExternalLink aria-hidden />
              {t("policy")}
            </a>
          </Button>
        ) : (
          <p className="text-muted-foreground text-sm">{t("noPolicy")}</p>
        )}
      </section>
      <section className="space-y-2 rounded-xl border p-4">
        <h2 className="font-semibold">{t("deleteTitle")}</h2>
        <p className="text-sm">{t("deleteBody")}</p>
        <p className="text-muted-foreground text-sm">{t("keptBody")}</p>
        <Button asChild variant="outline" className="min-h-11">
          <Link href="/shop/account/help">
            <LifeBuoy aria-hidden />
            {t("contact")}
          </Link>
        </Button>
      </section>
    </div>
  );
}
