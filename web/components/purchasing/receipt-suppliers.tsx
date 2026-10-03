"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "@/lib/i18n/translations";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { FormActions } from "@/components/shared/form-actions";
import { FormSelect } from "@/components/shared/form-select";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { TableSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  suppliersFromReceiptsConfirm,
  useSuppliersFromReceipts,
  useSuppliersList,
} from "@/lib/api/generated/endpoints/purchasing/purchasing";
import type { ReceiptSupplierName } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";

const SKIP = "skip";
const NEW = "new";

/**
 * The one-time review (ADR-053 item 4): supplier names typed on past goods receipts become
 * suppliers only when staff confirm them. A same-name supplier is offered first; a name can be
 * linked to another supplier or made a new one; the rest wait until staff choose.
 */
export function ReceiptSuppliersPage() {
  const t = useTranslations("purchasing.fromReceipts");
  const errors = useErrorText();
  const { can } = useAuth();
  const query = useSuppliersFromReceipts();
  const suppliers = useSuppliersList({ active: true, page_size: 100 });
  const rows = useMemo(() => query.data?.data ?? [], [query.data]);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const options = [
    { value: SKIP, label: t("later") },
    { value: NEW, label: t("createNew") },
    ...(suppliers.data?.data.results ?? []).map((s) => ({
      value: s.id,
      label: t("linkTo", { name: s.name }),
    })),
  ];
  // A same-name supplier is offered; anything else waits for staff to choose (no supplier is
  // made from a typo by one tap on Confirm).
  const choiceOf = (row: ReceiptSupplierName) => choices[row.name] ?? row.match_id ?? SKIP;
  const chosen = rows.filter((row) => choiceOf(row) !== SKIP);

  async function confirm() {
    setBusy(true);
    try {
      const result = await suppliersFromReceiptsConfirm({
        choices: chosen.map((row) => {
          const choice = choiceOf(row);
          return choice === NEW
            ? { name: row.name, new: true }
            : { name: row.name, supplier_id: choice };
        }),
      });
      toast.success(
        t("done", {
          created: result.data.suppliers_created,
          linked: result.data.receipts_linked,
        }),
      );
      setChoices({});
      void query.refetch();
      void suppliers.refetch();
    } catch (err) {
      toast.error(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Link
        href="/manage/purchasing/suppliers"
        className="text-muted-foreground hover:text-foreground mb-2 inline-flex min-h-11 items-center gap-1 text-sm"
      >
        <ArrowLeft aria-hidden className="size-4" />
        {t("back")}
      </Link>
      <PageHeader title={t("title")} description={t("description")} />
      {query.isLoading ? (
        <TableSkeleton rows={4} />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title={t("emptyTitle")} description={t("emptyBody")} />
      ) : (
        <div className="space-y-4">
          <ul className="space-y-3" aria-label={t("names")}>
            {rows.map((row) => (
              <li key={row.name}>
                <Card>
                  <CardContent className="grid gap-3 sm:grid-cols-[1fr_18rem] sm:items-center">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{row.name}</p>
                      <p className="text-muted-foreground text-sm">
                        {t("receipts", { count: row.receipts })}
                        {row.last_date ? (
                          <>
                            {" · "}
                            {t("last")} <DateText value={row.last_date} />
                          </>
                        ) : null}
                      </p>
                      {row.match_name ? (
                        <p className="text-muted-foreground text-xs">
                          {t("sameName", { name: row.match_name })}
                        </p>
                      ) : null}
                    </div>
                    <FormSelect
                      aria-label={t("choiceFor", { name: row.name })}
                      value={choiceOf(row)}
                      onValueChange={(value) => setChoices((c) => ({ ...c, [row.name]: value }))}
                      options={options}
                      disabled={!can("purchasing.manage")}
                    />
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
          {can("purchasing.manage") ? (
            <FormActions>
              <Button
                className="min-h-11"
                disabled={busy || chosen.length === 0}
                onClick={() => void confirm()}
              >
                {t("confirm", { count: chosen.length })}
              </Button>
            </FormActions>
          ) : null}
        </div>
      )}
    </>
  );
}
