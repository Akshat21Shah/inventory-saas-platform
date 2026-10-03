"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { DateText } from "@/components/shared/money-text";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  creditNoteEinvoiceRequest,
  einvoiceCancel,
  invoiceEinvoiceRequest,
  useEinvoiceReissuePreview,
} from "@/lib/api/generated/endpoints/compliance/compliance";
import type { EInvoiceSummary, IrnCancelReasonEnum } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatQty } from "@/lib/format";
import { ProviderMessage } from "@/components/shared/provider-message";
import { useTranslations } from "@/lib/i18n/translations";
import { useGstFailure } from "./provider-line";

const REASONS: IrnCancelReasonEnum[] = [
  "DATA_ENTRY_MISTAKE",
  "DUPLICATE",
  "ORDER_CANCELLED",
  "OTHER",
];
const IN_TRANSIT = new Set(["SUBMITTED", "CANCELLING"]);

/** Whether a document's e-invoice is on its way (the page follows it until it lands). */
export function einvoiceMoving(summary: EInvoiceSummary | null | undefined): boolean {
  if (!summary) return false;
  return IN_TRANSIT.has(summary.status) || (summary.status === "PENDING" && !!summary.requested_at);
}

/** Cancel an invoice's IRN within the window (ADR-049 item 7): re-issue a corrected invoice
 * (the default) or take the goods back. A re-issue keeps the original rates; when today's rate
 * differs, staff must confirm (backend checkpoint change 2). */
function CancelIrnDialog({ summary, onDone }: { summary: EInvoiceSummary; onDone: () => void }) {
  const t = useTranslations("compliance.einvoice.cancel");
  const tc = useTranslations("common");
  const { message, fields } = useErrorText();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<IrnCancelReasonEnum>("DATA_ENTRY_MISTAKE");
  const [remarks, setRemarks] = useState("");
  const [outcome, setOutcome] = useState<"REISSUE" | "TAKE_BACK">("REISSUE");
  const [toBackorder, setToBackorder] = useState(true);
  const [confirmRates, setConfirmRates] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const preview = useEinvoiceReissuePreview(summary.id, {
    query: { enabled: open && outcome === "REISSUE" },
  });
  const rates = preview.data?.data.rate_changes ?? [];
  const buyer = preview.data?.data;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setErrors({});
    try {
      await einvoiceCancel(summary.id, {
        reason_code: reason,
        remarks,
        outcome,
        to_backorder: outcome === "TAKE_BACK" && toBackorder,
        confirm_rate_changes: confirmRates,
      });
      toast.success(t("started"));
      setOpen(false);
      onDone();
    } catch (err) {
      const byField = fields(err);
      setErrors(byField);
      if (!Object.keys(byField).length) toast.error(message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" className="min-h-10">
          {t("button")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <form onSubmit={submit} className="space-y-4" noValidate>
          <DialogHeader>
            <DialogTitle>{t("title")}</DialogTitle>
            <DialogDescription>
              {summary.cancel_until
                ? t.rich("body", {
                    until: () => <DateText value={summary.cancel_until ?? ""} withTime />,
                  })
                : null}
            </DialogDescription>
          </DialogHeader>
          <FormField label={t("reason")} error={errors.reason_code}>
            <FormSelect
              value={reason}
              onValueChange={(value) => setReason(value as IrnCancelReasonEnum)}
              options={REASONS.map((value) => ({ value, label: t(`reasons.${value}`) }))}
            />
          </FormField>
          <FormField
            label={t("remarks")}
            required={reason === "OTHER"}
            error={errors.remarks}
            hint={t("remarksHint")}
          >
            <Textarea rows={2} value={remarks} onChange={(e) => setRemarks(e.target.value)} />
          </FormField>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">{t("outcome")}</legend>
            {(["REISSUE", "TAKE_BACK"] as const).map((value) => (
              <label
                key={value}
                className="flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border p-3"
              >
                <input
                  type="radio"
                  name="outcome"
                  value={value}
                  checked={outcome === value}
                  onChange={() => setOutcome(value)}
                  className="mt-1 size-4"
                />
                <span>
                  <span className="block text-sm font-medium">{t(`outcomes.${value}`)}</span>
                  <span className="text-muted-foreground block text-xs">
                    {t(`outcomeHints.${value}`)}
                  </span>
                </span>
              </label>
            ))}
            {errors.outcome ? <p className="text-destructive text-sm">{errors.outcome}</p> : null}
          </fieldset>
          {outcome === "TAKE_BACK" ? (
            <FormField label={t("quantities")} error={errors.to_backorder}>
              <FormSelect
                value={toBackorder ? "backorder" : "cancel"}
                onValueChange={(value) => setToBackorder(value === "backorder")}
                options={[
                  { value: "backorder", label: t("toBackorder") },
                  { value: "cancel", label: t("toCancel") },
                ]}
              />
            </FormField>
          ) : buyer ? (
            <div className="space-y-2 rounded-lg border p-3 text-sm" aria-live="polite">
              <p className="font-medium">{t("reissueTo")}</p>
              <p>
                {buyer.buyer.name}
                {buyer.buyer.gstin ? ` · ${buyer.buyer.gstin}` : ""}
                {buyer.buyer_changed ? (
                  <span className="text-info-strong"> · {t("detailsChanged")}</span>
                ) : null}
              </p>
              {buyer.supply_type !== buyer.supply_type_before ? (
                <p className="text-warning-strong">{t(`supplyChange.${buyer.supply_type}`)}</p>
              ) : null}
              {rates.length ? (
                <div className="bg-warning/15 space-y-2 rounded-lg p-3">
                  <p className="flex gap-2 font-medium">
                    <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
                    {t("ratesChanged")}
                  </p>
                  <ul className="space-y-1">
                    {rates.map((line) => (
                      <li key={line.line_no}>
                        {t("rateLine", {
                          item: line.description,
                          original: formatQty(line.original_rate),
                          today: formatQty(line.today_rate),
                        })}
                      </li>
                    ))}
                  </ul>
                  <label className="flex min-h-11 items-center gap-3">
                    <Checkbox
                      checked={confirmRates}
                      onCheckedChange={(checked) => setConfirmRates(checked === true)}
                      aria-label={t("keepRates")}
                    />
                    <span>{t("keepRates")}</span>
                  </label>
                  {errors.confirm_rate_changes ? (
                    <p className="text-destructive">{errors.confirm_rate_changes}</p>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
          {errors.document ? (
            <p role="alert" className="text-destructive text-sm font-medium">
              {errors.document}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              {tc("cancel")}
            </Button>
            <Button
              type="submit"
              variant="destructive"
              className="min-h-10"
              disabled={busy || (outcome === "REISSUE" && rates.length > 0 && !confirmRates)}
            >
              {t("confirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** A document's IRN (ADR-049): its status, the portal's reason when it failed, the reporting
 * limit, and "Get IRN" / "Try again" / "Cancel IRN" for staff who manage compliance. */
export function EInvoicePanel({
  kind,
  documentId,
  summary,
  registeredBuyer,
  onChanged,
}: {
  kind: "invoice" | "credit_note";
  documentId: string;
  summary: EInvoiceSummary | null;
  /** The shop has a GSTIN: only then does a document get an IRN. */
  registeredBuyer: boolean;
  onChanged: () => void;
}) {
  const t = useTranslations("compliance.einvoice");
  const tp = useTranslations("providerMessages");
  const gst = useGstFailure();
  const { can, feature } = useAuth();
  const { message } = useErrorText();
  const [busy, setBusy] = useState(false);
  const manage = can("compliance.manage");
  if (!summary && !(feature("einvoice") && registeredBuyer)) return null;

  async function request() {
    setBusy(true);
    try {
      if (kind === "invoice") await invoiceEinvoiceRequest(documentId);
      else await creditNoteEinvoiceRequest(documentId);
      toast.success(t("requested"));
      onChanged();
    } catch (err) {
      toast.error(message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      id="einvoice"
      className="space-y-3 rounded-xl border p-4"
      aria-labelledby="einvoice-heading"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="einvoice-heading" className="font-semibold">
          {t("title")}
        </h2>
        {summary ? <StatusBadge status={summary.status} labels="einvoiceStatus" /> : null}
      </div>
      {!summary ? (
        <p className="text-muted-foreground text-sm">{t("none")}</p>
      ) : (
        <>
          {summary.irn ? (
            <dl className="grid gap-2 text-sm">
              <div>
                <dt className="text-muted-foreground">{t("irn")}</dt>
                <dd className="font-mono text-xs break-all">{summary.irn}</dd>
              </div>
              <div className="flex flex-wrap gap-x-6 gap-y-1">
                <span>
                  <span className="text-muted-foreground">{t("ackNo")} </span>
                  {summary.ack_no}
                </span>
                {summary.ack_date ? (
                  <span>
                    <span className="text-muted-foreground">{t("ackDate")} </span>
                    <DateText value={summary.ack_date} withTime />
                  </span>
                ) : null}
              </div>
            </dl>
          ) : null}
          {summary.status === "PENDING" && !summary.requested_at ? (
            <p className="text-sm">{t("waiting")}</p>
          ) : null}
          {summary.status === "PENDING" && summary.next_retry_at ? (
            <p className="text-sm">
              <ProviderMessage
                line={tp.rich("portalRetrying", {
                  at: () => <DateText value={summary.next_retry_at ?? ""} withTime />,
                })}
                message={summary.error_message}
              />
            </p>
          ) : null}
          {IN_TRANSIT.has(summary.status) ? (
            <p className="text-muted-foreground text-sm" aria-live="polite">
              {t(summary.status === "CANCELLING" ? "cancelling" : "sending")}
            </p>
          ) : null}
          {summary.status === "FAILED" ? (
            <p role="alert" className="bg-destructive/10 rounded-lg p-3 text-sm">
              <ProviderMessage {...gst("einvoice", summary.error_code, summary.error_message)} />
              <span className="mt-1 block">{t("failedHint")}</span>
            </p>
          ) : null}
          {summary.report_by ? (
            <p
              className={
                summary.past_report_by
                  ? "bg-destructive/10 rounded-lg p-3 text-sm"
                  : "bg-warning/15 rounded-lg p-3 text-sm"
              }
            >
              {t.rich(summary.past_report_by ? "pastReportBy" : "reportBy", {
                day: () => <DateText value={summary.report_by ?? ""} />,
              })}
            </p>
          ) : null}
          {summary.cancel_error && summary.status === "GENERATED" ? (
            <p role="alert" className="bg-destructive/10 rounded-lg p-3 text-sm">
              {t("cancelRefused", { error: summary.cancel_error })}
            </p>
          ) : null}
          {summary.status === "CANCELLED" ? (
            <p className="text-sm">
              {t.rich("cancelled", {
                at: () => <DateText value={summary.cancelled_at ?? ""} withTime />,
              })}{" "}
              {summary.reissued_invoice ? (
                <Link
                  href={`/manage/invoices/${summary.reissued_invoice.id}`}
                  className="font-medium hover:underline"
                >
                  {t("reissuedAs", { number: summary.reissued_invoice.number })}
                </Link>
              ) : summary.cancel_outcome === "TAKE_BACK" ? (
                t("takenBack")
              ) : null}
            </p>
          ) : null}
          {kind === "invoice" && summary.status === "GENERATED" && summary.cancel_blocked ? (
            summary.cancel_blocked.reason !== "WINDOW_OVER" ? (
              <p className="text-muted-foreground text-sm">
                {summary.cancel_blocked.message}
                {summary.cancel_blocked.reason === "EWAY_BILL" ? (
                  <>
                    {" "}
                    <a href="#ewaybill" className="font-medium hover:underline">
                      {t("toEwaybill")}
                    </a>
                  </>
                ) : null}
              </p>
            ) : null
          ) : null}
        </>
      )}
      {manage ? (
        <div className="flex flex-wrap gap-2">
          {!summary || summary.can_request ? (
            <Button className="min-h-10 gap-2" disabled={busy} onClick={() => void request()}>
              <RefreshCw aria-hidden className="size-4" />
              {summary?.status === "FAILED" ? t("tryAgain") : t("get")}
            </Button>
          ) : null}
          {kind === "invoice" && summary?.can_cancel ? (
            <CancelIrnDialog summary={summary} onDone={onChanged} />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
