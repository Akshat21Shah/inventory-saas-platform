"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { ErrorState } from "@/components/shared/error-state";
import { CardSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  getSettingsDocumentSeriesQueryKey,
  settingsDocumentSeriesChange,
  useSettingsDocumentSeries,
} from "@/lib/api/generated/endpoints/settings/settings";
import type { DocumentSeries } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";

function SeriesRow({ row, canEdit }: { row: DocumentSeries; canEdit: boolean }) {
  const t = useTranslations("billing.numbering");
  const client = useQueryClient();
  const { message } = useErrorText();
  const [prefix, setPrefix] = useState(row.prefix);
  const [busy, setBusy] = useState(false);
  const changed = prefix.trim().toUpperCase() !== row.prefix;
  return (
    <li className="flex flex-wrap items-end justify-between gap-3 py-3">
      <div className="min-w-0">
        <p className="font-medium">{t(`types.${row.document_type}`)}</p>
        <p className="text-muted-foreground text-xs">
          {t("next", { number: row.next_number })} · {t("issued", { count: row.issued })}
        </p>
      </div>
      {canEdit ? (
        <form
          className="flex items-end gap-2"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            try {
              const response = await settingsDocumentSeriesChange({
                document_type: row.document_type,
                prefix: prefix.trim().toUpperCase(),
              });
              client.setQueryData(getSettingsDocumentSeriesQueryKey(), response);
              toast.success(t("saved"));
            } catch (error) {
              toast.error(message(error));
            } finally {
              setBusy(false);
            }
          }}
        >
          <label className="flex flex-col gap-1 text-xs">
            {t("prefix")}
            <Input
              className="min-h-10 w-20 uppercase"
              maxLength={3}
              value={prefix}
              onChange={(e) => setPrefix(e.target.value.toUpperCase())}
            />
          </label>
          <Button type="submit" variant="outline" className="min-h-10" disabled={busy || !changed}>
            {t("save")}
          </Button>
        </form>
      ) : null}
    </li>
  );
}

/** Invoice, credit note, receipt and refund numbers (ADR-046 item 1): a prefix of 1 to 3
 * letters or digits, the financial year and a 6-digit number, restarting each April. */
export function DocumentNumbering() {
  const t = useTranslations("billing.numbering");
  const { can } = useAuth();
  const query = useSettingsDocumentSeries();
  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>
          <h2 className="text-lg">{t("title")}</h2>
        </CardTitle>
        <CardDescription>{t("body")}</CardDescription>
      </CardHeader>
      <CardContent>
        {query.isLoading ? (
          <CardSkeleton />
        ) : query.error ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <ul className="divide-y">
            {(query.data?.data ?? []).map((row) => (
              <SeriesRow
                key={`${row.document_type}-${row.prefix}`}
                row={row}
                canEdit={can("settings.manage")}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
