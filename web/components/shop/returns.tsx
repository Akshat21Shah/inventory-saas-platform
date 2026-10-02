"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
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
  getShopInvoicesRetrieveQueryKey,
  shopReturnRequestsCancel,
  shopReturnRequestsCreate,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { ReturnReasonEnum, ShopInvoiceDetail } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatQty } from "@/lib/format";

const REASONS: ReturnReasonEnum[] = ["DAMAGED", "EXPIRED", "WRONG_ITEM", "EXCESS_SUPPLY", "OTHER"];

function useRefreshBill(billId: string) {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: getShopInvoicesRetrieveQueryKey(billId) });
}

/** "Return items": the shop picks quantities up to what may still be returned, and why
 * (ADR-057 item 3). Nothing moves until the distributor approves. */
export function ReturnItemsButton({ bill }: { bill: ShopInvoiceDetail }) {
  const t = useTranslations("shop.returns");
  const errors = useErrorText();
  const refresh = useRefreshBill(bill.id);
  const left = new Map(bill.returnable.map((row) => [row.invoice_line_id, row.quantity]));
  const lines = bill.lines.filter((line) => Number(left.get(line.id) ?? 0) > 0);
  const [open, setOpen] = useState(false);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [reason, setReason] = useState<ReturnReasonEnum>("DAMAGED");
  const [note, setNote] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  if (!bill.can_request_return || lines.length === 0) return null;

  const chosen = Object.entries(quantities).filter(([, q]) => Number(q) > 0);
  async function send() {
    setBusy(true);
    setFieldErrors({});
    try {
      await shopReturnRequestsCreate({
        invoice: bill.id,
        reason,
        note: note.trim(),
        lines: chosen.map(([line, quantity]) => ({ invoice_line: line, quantity })),
      });
      toast.success(t("sent"));
      setOpen(false);
      setQuantities({});
      setNote("");
      await refresh();
    } catch (err) {
      const fields = errors.fields(err);
      setFieldErrors(fields);
      if (Object.keys(fields).length === 0) toast.error(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" className="min-h-11">
          <Undo2 aria-hidden />
          {t("open")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("body")}</DialogDescription>
        </DialogHeader>
        <ul className="max-h-[45vh] space-y-3 overflow-y-auto">
          {lines.map((line) => (
            <li key={line.id} className="flex items-center justify-between gap-3 text-sm">
              <label htmlFor={`return-${line.id}`} className="min-w-0">
                <span className="block font-medium">{line.description}</span>
                <span className="text-muted-foreground text-xs">
                  {t("upTo", { qty: formatQty(left.get(line.id) ?? "0"), unit: line.unit_code })}
                </span>
              </label>
              <Input
                id={`return-${line.id}`}
                inputMode="decimal"
                placeholder="0"
                value={quantities[line.id] ?? ""}
                onChange={(e) => setQuantities((q) => ({ ...q, [line.id]: e.target.value }))}
                className="min-h-11 w-24 text-right"
              />
            </li>
          ))}
        </ul>
        {fieldErrors.lines ? (
          <p role="alert" className="text-destructive text-sm font-medium">
            {fieldErrors.lines}
          </p>
        ) : null}
        <FormField label={t("reason")} error={fieldErrors.reason}>
          <FormSelect
            value={reason}
            onValueChange={(v) => setReason(v as ReturnReasonEnum)}
            options={REASONS.map((code) => ({ value: code, label: t(`reasons.${code}`) }))}
          />
        </FormField>
        <FormField label={t("note")} error={fieldErrors.note} hint={t("noteHint")}>
          <Textarea value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
        </FormField>
        <DialogFooter>
          <Button variant="outline" className="min-h-11" onClick={() => setOpen(false)}>
            {t("cancel")}
          </Button>
          <Button
            className="min-h-11"
            disabled={busy || chosen.length === 0}
            onClick={() => void send()}
          >
            {t("send")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The bill's return requests: what was asked, where it stands, and cancel while it waits. */
export function BillReturns({ bill }: { bill: ShopInvoiceDetail }) {
  const t = useTranslations("shop.returns");
  const refresh = useRefreshBill(bill.id);
  if (bill.return_requests.length === 0) return null;
  return (
    <section className="space-y-2" aria-labelledby="bill-returns">
      <h2 id="bill-returns" className="font-semibold">
        {t("heading")}
      </h2>
      <ul className="divide-y rounded-xl border">
        {bill.return_requests.map((request) => (
          <li key={request.id} className="space-y-1.5 p-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">{request.number}</span>
              <StatusBadge status={request.status} labels="shopReturnStatus" />
            </div>
            <p className="text-muted-foreground">
              {request.lines
                .map((line) => `${formatQty(line.quantity)} ${line.description}`)
                .join(", ")}
            </p>
            {request.status === "REJECTED" && request.decision_note ? (
              <p>{t("why", { reason: request.decision_note })}</p>
            ) : null}
            {request.credit_note ? (
              <p>{t("credited", { number: request.credit_note.number })}</p>
            ) : null}
            {request.status === "REQUESTED" ? (
              <ConfirmDialog
                trigger={
                  <Button variant="outline" size="sm" className="min-h-11">
                    {t("withdraw")}
                  </Button>
                }
                title={t("withdrawTitle", { number: request.number })}
                confirmLabel={t("withdraw")}
                onConfirm={async () => {
                  await shopReturnRequestsCancel(request.id);
                  await refresh();
                }}
              />
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
