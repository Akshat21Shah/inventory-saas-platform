"use client";

import { Truck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { DateText } from "@/components/shared/money-text";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ewaybillCancel,
  ewaybillPartB,
  invoiceEwaybillRequest,
} from "@/lib/api/generated/endpoints/compliance/compliance";
import {
  IrnCancelReasonEnum,
  PartBInputReasonCodeEnum,
  TransportModeEnum,
  type EWayBillSummary,
} from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";

/** Whether an e-way bill is on its way (the page follows it until it lands). */
export function ewaybillMoving(summary: EWayBillSummary | null | undefined): boolean {
  if (!summary) return false;
  return (
    summary.status === "SUBMITTED" ||
    (summary.status === "PENDING" && !!summary.requested_at) ||
    !!summary.pending_update
  );
}

/** The fields the server refused that belong to no input: shown above the buttons. */
const DOCUMENT_FIELDS = ["invoice", "ewaybill", "document"];

/** A dialog with a form; the server's refusals land on the fields, the rest in a toast. */
function ActionDialog({
  trigger,
  title,
  description,
  submitLabel,
  destructive,
  onSubmit,
  onDone,
  children,
}: {
  trigger: ReactNode;
  title: string;
  description?: ReactNode;
  submitLabel: string;
  destructive?: boolean;
  onSubmit: () => Promise<unknown>;
  onDone: () => void;
  children: (errors: Record<string, string>) => ReactNode;
}) {
  const tc = useTranslations("common");
  const { message, fields } = useErrorText();
  const [open, setOpen] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setErrors({});
    try {
      await onSubmit();
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

  const general = DOCUMENT_FIELDS.map((name) => errors[name]).filter(Boolean);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setErrors({});
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <form onSubmit={submit} className="space-y-4" noValidate>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description ? <DialogDescription>{description}</DialogDescription> : null}
          </DialogHeader>
          {children(errors)}
          {general.map((text) => (
            <p key={text} role="alert" className="text-destructive text-sm font-medium">
              {text}
            </p>
          ))}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              {tc("cancel")}
            </Button>
            <Button
              type="submit"
              variant={destructive ? "destructive" : "default"}
              className="min-h-10"
              disabled={busy}
            >
              {submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** "Make e-way bill" / "Try again": the transport details (a failed one's are filled in to
 * correct). The distance comes from the shop's address when left blank. */
function TransportDialog({
  invoiceId,
  summary,
  onDone,
}: {
  invoiceId: string;
  summary: EWayBillSummary | null;
  onDone: () => void;
}) {
  const t = useTranslations("compliance.ewaybill");
  const [mode, setMode] = useState<TransportModeEnum>(summary?.transport_mode ?? "ROAD");
  const [vehicle, setVehicle] = useState(summary?.vehicle_number ?? "");
  const [transporterId, setTransporterId] = useState(summary?.transporter_id ?? "");
  const [transporterName, setTransporterName] = useState(summary?.transporter_name ?? "");
  const [docNo, setDocNo] = useState(summary?.transport_doc_no ?? "");
  const [docDate, setDocDate] = useState(summary?.transport_doc_date ?? "");
  const [distance, setDistance] = useState(summary?.distance_km ? String(summary.distance_km) : "");
  const retry = summary?.status === "FAILED";
  return (
    <ActionDialog
      trigger={
        <Button className="min-h-10 gap-2">
          <Truck aria-hidden className="size-4" />
          {retry ? t("tryAgain") : t("make")}
        </Button>
      }
      title={retry ? t("retryTitle") : t("makeTitle")}
      description={t("transportBody")}
      submitLabel={retry ? t("tryAgain") : t("make")}
      onSubmit={async () => {
        await invoiceEwaybillRequest(invoiceId, {
          transport_mode: mode,
          vehicle_number: vehicle.trim(),
          transporter_id: transporterId.trim(),
          transporter_name: transporterName.trim(),
          transport_doc_no: docNo.trim(),
          transport_doc_date: docDate || null,
          ...(distance ? { distance_km: Number(distance) } : {}),
        });
        toast.success(t("requested"));
      }}
      onDone={onDone}
    >
      {(errors) => (
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label={t("mode")} error={errors.transport_mode}>
            <FormSelect
              value={mode}
              onValueChange={(value) => setMode(value as TransportModeEnum)}
              options={Object.values(TransportModeEnum).map((value) => ({
                value,
                label: t(`modes.${value}`),
              }))}
            />
          </FormField>
          <FormField
            label={t("vehicle")}
            required={mode === "ROAD" && !transporterId.trim()}
            hint={t("vehicleHint")}
            error={errors.vehicle_number}
          >
            <Input
              className="h-10 uppercase"
              maxLength={20}
              value={vehicle}
              onChange={(e) => setVehicle(e.target.value)}
            />
          </FormField>
          <FormField
            label={t("transporterId")}
            hint={t("transporterIdHint")}
            error={errors.transporter_id}
          >
            <Input
              className="h-10 uppercase"
              maxLength={15}
              value={transporterId}
              onChange={(e) => setTransporterId(e.target.value)}
            />
          </FormField>
          <FormField label={t("transporterName")} error={errors.transporter_name}>
            <Input
              className="h-10"
              maxLength={120}
              value={transporterName}
              onChange={(e) => setTransporterName(e.target.value)}
            />
          </FormField>
          <FormField label={t("docNo")} hint={t("docNoHint")} error={errors.transport_doc_no}>
            <Input
              className="h-10"
              maxLength={40}
              value={docNo}
              onChange={(e) => setDocNo(e.target.value)}
            />
          </FormField>
          <FormField label={t("docDate")} error={errors.transport_doc_date}>
            <Input
              className="h-10"
              type="date"
              value={docDate}
              onChange={(e) => setDocDate(e.target.value)}
            />
          </FormField>
          <FormField label={t("distance")} hint={t("distanceHint")} error={errors.distance_km}>
            <Input
              className="h-10"
              type="number"
              inputMode="numeric"
              min={1}
              max={4000}
              value={distance}
              onChange={(e) => setDistance(e.target.value)}
            />
          </FormField>
        </div>
      )}
    </ActionDialog>
  );
}

/** A new vehicle (Part-B) while the goods are on the way. */
function PartBDialog({ summary, onDone }: { summary: EWayBillSummary; onDone: () => void }) {
  const t = useTranslations("compliance.ewaybill");
  const [vehicle, setVehicle] = useState("");
  const [docNo, setDocNo] = useState("");
  const [reason, setReason] = useState<PartBInputReasonCodeEnum>("BREAKDOWN");
  const [remarks, setRemarks] = useState("");
  return (
    <ActionDialog
      trigger={
        <Button variant="outline" className="min-h-10">
          {t("changeVehicle")}
        </Button>
      }
      title={t("partBTitle")}
      description={t("partBBody", { number: summary.ewb_number })}
      submitLabel={t("sendChange")}
      onSubmit={async () => {
        await ewaybillPartB(summary.id, {
          vehicle_number: vehicle.trim(),
          transport_doc_no: docNo.trim(),
          reason_code: reason,
          remarks,
        });
        toast.success(t("changeSent"));
      }}
      onDone={onDone}
    >
      {(errors) => (
        <div className="space-y-4">
          <FormField label={t("newVehicle")} required error={errors.vehicle_number}>
            <Input
              className="h-10 uppercase"
              maxLength={20}
              value={vehicle}
              onChange={(e) => setVehicle(e.target.value)}
            />
          </FormField>
          <FormField label={t("docNo")} error={errors.transport_doc_no}>
            <Input
              className="h-10"
              maxLength={40}
              value={docNo}
              onChange={(e) => setDocNo(e.target.value)}
            />
          </FormField>
          <FormField label={t("reason")} error={errors.reason_code}>
            <FormSelect
              value={reason}
              onValueChange={(value) => setReason(value as PartBInputReasonCodeEnum)}
              options={Object.values(PartBInputReasonCodeEnum).map((value) => ({
                value,
                label: t(`partBReasons.${value}`),
              }))}
            />
          </FormField>
          <FormField label={t("remarks")} required={reason === "OTHER"} error={errors.remarks}>
            <Textarea
              rows={2}
              maxLength={100}
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
            />
          </FormField>
        </div>
      )}
    </ActionDialog>
  );
}

function CancelDialog({ summary, onDone }: { summary: EWayBillSummary; onDone: () => void }) {
  const t = useTranslations("compliance.ewaybill");
  const reasons = useTranslations("compliance.einvoice.cancel.reasons");
  const [reason, setReason] = useState<IrnCancelReasonEnum>("DATA_ENTRY_MISTAKE");
  const [remarks, setRemarks] = useState("");
  return (
    <ActionDialog
      trigger={
        <Button variant="outline" className="min-h-10">
          {t("cancel")}
        </Button>
      }
      title={t("cancelTitle", { number: summary.ewb_number })}
      description={
        summary.cancel_until
          ? t.rich("cancelBody", {
              until: () => <DateText value={summary.cancel_until ?? ""} withTime />,
            })
          : undefined
      }
      submitLabel={t("cancelConfirm")}
      destructive
      onSubmit={async () => {
        await ewaybillCancel(summary.id, { reason_code: reason, remarks });
        toast.success(t("cancelSent"));
      }}
      onDone={onDone}
    >
      {(errors) => (
        <div className="space-y-4">
          <FormField label={t("reason")} error={errors.reason_code}>
            <FormSelect
              value={reason}
              onValueChange={(value) => setReason(value as IrnCancelReasonEnum)}
              options={Object.values(IrnCancelReasonEnum).map((value) => ({
                value,
                label: reasons(value),
              }))}
            />
          </FormField>
          <FormField label={t("remarks")} required={reason === "OTHER"} error={errors.remarks}>
            <Textarea
              rows={2}
              maxLength={100}
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
            />
          </FormField>
        </div>
      )}
    </ActionDialog>
  );
}

/** An invoice's e-way bill (ADR-049): made on dispatch above the threshold, or by hand; a
 * failed one names the portal's reason and can be tried again with corrected details. */
export function EWayBillPanel({
  invoiceId,
  summary,
  cancelled,
  onChanged,
}: {
  invoiceId: string;
  summary: EWayBillSummary | null;
  /** The invoice itself is cancelled: nothing new can be made. */
  cancelled: boolean;
  onChanged: () => void;
}) {
  const t = useTranslations("compliance.ewaybill");
  const { can, feature } = useAuth();
  if (!summary && !(feature("ewaybill") && !cancelled)) return null;
  const manage = can("compliance.manage");
  const modes = (mode: string) => t(`modes.${mode}`);

  return (
    <section
      id="ewaybill"
      className="space-y-3 rounded-xl border p-4"
      aria-labelledby="ewaybill-heading"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="ewaybill-heading" className="font-semibold">
          {t("title")}
        </h2>
        {summary ? <StatusBadge status={summary.status} labels="ewaybillStatus" /> : null}
      </div>
      {!summary ? (
        <p className="text-muted-foreground text-sm">{t("none")}</p>
      ) : (
        <>
          {summary.ewb_number ? (
            <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">{t("number")}</dt>
                <dd className="font-mono">{summary.ewb_number}</dd>
              </div>
              {summary.valid_until ? (
                <div>
                  <dt className="text-muted-foreground">{t("validUntil")}</dt>
                  <dd>
                    <DateText value={summary.valid_until} withTime />
                  </dd>
                </div>
              ) : null}
            </dl>
          ) : null}
          <p className="text-sm">
            {[
              modes(summary.transport_mode),
              summary.vehicle_number,
              summary.transporter_name || summary.transporter_id,
              summary.distance_km ? t("km", { km: summary.distance_km }) : "",
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {summary.status === "PENDING" && !summary.requested_at ? (
            <p className="text-sm">{t("waiting")}</p>
          ) : null}
          {summary.status === "PENDING" && summary.next_retry_at ? (
            <p className="text-sm">
              {t.rich("retrying", {
                error: summary.error_message,
                at: () => <DateText value={summary.next_retry_at ?? ""} withTime />,
              })}
            </p>
          ) : null}
          {summary.status === "SUBMITTED" ? (
            <p className="text-muted-foreground text-sm" aria-live="polite">
              {t("sending")}
            </p>
          ) : null}
          {summary.status === "FAILED" ? (
            <p role="alert" className="bg-destructive/10 rounded-lg p-3 text-sm">
              {t("failed", { error: summary.error_message })}
            </p>
          ) : null}
          {summary.pending_update ? (
            <p className="text-muted-foreground text-sm" aria-live="polite">
              {t(summary.pending_update === "CANCEL" ? "cancelling" : "changing")}
            </p>
          ) : null}
          {summary.last_update_error && !summary.pending_update ? (
            <p role="alert" className="bg-destructive/10 rounded-lg p-3 text-sm">
              {t("updateRefused", { error: summary.last_update_error })}
            </p>
          ) : null}
          {summary.status === "CANCELLED" && summary.cancelled_at ? (
            <p className="text-sm">
              {t.rich("cancelled", {
                at: () => <DateText value={summary.cancelled_at ?? ""} withTime />,
              })}
            </p>
          ) : null}
        </>
      )}
      {manage ? (
        <div className="flex flex-wrap gap-2">
          {(!summary || summary.can_request) && !cancelled ? (
            <TransportDialog invoiceId={invoiceId} summary={summary} onDone={onChanged} />
          ) : null}
          {summary?.can_update ? <PartBDialog summary={summary} onDone={onChanged} /> : null}
          {summary?.can_cancel ? <CancelDialog summary={summary} onDone={onChanged} /> : null}
        </div>
      ) : null}
    </section>
  );
}
