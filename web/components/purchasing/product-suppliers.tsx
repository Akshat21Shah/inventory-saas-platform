"use client";

import { Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FormSelect } from "@/components/shared/form-select";
import { MoneyText, QtyText } from "@/components/shared/money-text";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  productSuppliersSet,
  useProductSuppliersList,
  useSuppliersList,
} from "@/lib/api/generated/endpoints/purchasing/purchasing";
import type { SupplierProduct } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";

interface Row {
  supplier_id: string;
  supplier_code: string;
  lead_time_days: string;
  pack_size: string;
}

/** Who a product is bought from (purchasing on): codes, delivery days, packs and the last cost
 * (with costs.view); one is preferred. */
export function ProductSuppliersPanel({ productId }: { productId: string }) {
  const t = useTranslations("purchasing.productSuppliers");
  const { can } = useAuth();
  const query = useProductSuppliersList(productId);
  const links = query.data?.data ?? [];
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-base">{t("title")}</CardTitle>
        {can("purchasing.manage") && !query.isLoading && !query.error ? (
          <EditSuppliers productId={productId} links={links} onSaved={() => void query.refetch()} />
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {query.isLoading ? (
          <Skeleton className="h-12 w-full" />
        ) : query.error ? (
          <p role="alert" className="text-destructive">
            {t("failed")}{" "}
            <button type="button" className="underline" onClick={() => void query.refetch()}>
              {t("retry")}
            </button>
          </p>
        ) : links.length === 0 ? (
          <p className="text-muted-foreground">{t("none")}</p>
        ) : (
          <ul className="space-y-2">
            {links.map((link) => (
              <li key={link.id} className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <Link
                    href={`/manage/purchasing/suppliers/${link.supplier_id}`}
                    className="font-medium hover:underline"
                  >
                    {link.supplier_name}
                  </Link>{" "}
                  {link.is_preferred ? <Badge variant="secondary">{t("preferred")}</Badge> : null}
                  <p className="text-muted-foreground text-xs">
                    {[
                      link.supplier_code ? t("theirCode", { code: link.supplier_code }) : "",
                      link.lead_time_days ? t("days", { count: link.lead_time_days }) : "",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                    {link.pack_size ? (
                      <>
                        {link.supplier_code || link.lead_time_days ? " · " : ""}
                        {t("packOf")} <QtyText value={link.pack_size} />
                      </>
                    ) : null}
                  </p>
                </div>
                {link.last_unit_cost ? (
                  <span className="text-right text-xs">
                    <span className="text-muted-foreground block">{t("lastCost")}</span>
                    <MoneyText value={link.last_unit_cost} />
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function toRow(link: SupplierProduct): Row {
  return {
    supplier_id: link.supplier_id,
    supplier_code: link.supplier_code,
    lead_time_days: link.lead_time_days ? String(link.lead_time_days) : "",
    pack_size: link.pack_size ? String(Number(link.pack_size)) : "",
  };
}

function EditSuppliers({
  productId,
  links,
  onSaved,
}: {
  productId: string;
  links: SupplierProduct[];
  onSaved: () => void;
}) {
  const t = useTranslations("purchasing.productSuppliers");
  const errors = useErrorText();
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<Row[]>([]);
  const [preferred, setPreferred] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const suppliers = useSuppliersList(
    { active: true, page_size: 100 },
    { query: { enabled: open } },
  );
  const options = (suppliers.data?.data.results ?? []).map((s) => ({ value: s.id, label: s.name }));

  function reset() {
    setRows(links.map(toRow));
    setPreferred(links.find((l) => l.is_preferred)?.supplier_id ?? "");
    setError(null);
  }

  function update(index: number, change: Partial<Row>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...change } : row)));
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const chosen = rows.filter((row) => row.supplier_id);
      await productSuppliersSet(productId, {
        links: chosen.map((row) => ({
          supplier_id: row.supplier_id,
          is_preferred: row.supplier_id === preferred,
          supplier_code: row.supplier_code.trim(),
          lead_time_days: row.lead_time_days ? Number(row.lead_time_days) : null,
          pack_size: row.pack_size.trim() || null,
        })),
      });
      toast.success(t("saved"));
      setOpen(false);
      onSaved();
    } catch (err) {
      const fields = errors.fields(err);
      setError(fields.links ?? Object.values(fields)[0] ?? errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" className="min-h-9">
          <Pencil aria-hidden />
          {t("edit")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("editTitle")}</DialogTitle>
          <DialogDescription>{t("editBody")}</DialogDescription>
        </DialogHeader>
        <ul className="space-y-4">
          {rows.map((row, index) => (
            <li key={index} className="grid gap-3 rounded-lg border p-3 sm:grid-cols-2">
              <div className="space-y-1 sm:col-span-2">
                <Label>{t("supplier")}</Label>
                <FormSelect
                  aria-label={t("supplier")}
                  value={row.supplier_id}
                  onValueChange={(value) => update(index, { supplier_id: value })}
                  options={options}
                  placeholder={t("chooseSupplier")}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor={`code-${index}`}>{t("supplierCode")}</Label>
                <Input
                  id={`code-${index}`}
                  className="h-10"
                  value={row.supplier_code}
                  onChange={(e) => update(index, { supplier_code: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor={`days-${index}`}>{t("deliveryDays")}</Label>
                <Input
                  id={`days-${index}`}
                  inputMode="numeric"
                  className="h-10"
                  placeholder={t("supplierUsual")}
                  value={row.lead_time_days}
                  onChange={(e) => update(index, { lead_time_days: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor={`pack-${index}`}>{t("packSize")}</Label>
                <Input
                  id={`pack-${index}`}
                  inputMode="decimal"
                  className="h-10"
                  value={row.pack_size}
                  onChange={(e) => update(index, { pack_size: e.target.value })}
                />
              </div>
              <div className="flex items-end justify-between gap-2">
                <label className="flex min-h-11 items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="preferred"
                    className="size-4"
                    checked={Boolean(row.supplier_id) && preferred === row.supplier_id}
                    disabled={!row.supplier_id}
                    onChange={() => setPreferred(row.supplier_id)}
                  />
                  {t("preferred")}
                </label>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-11"
                  aria-label={t("remove")}
                  onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
                >
                  <Trash2 aria-hidden />
                </Button>
              </div>
            </li>
          ))}
        </ul>
        <Button
          type="button"
          variant="outline"
          className="min-h-11"
          onClick={() =>
            setRows((current) => [
              ...current,
              { supplier_id: "", supplier_code: "", lead_time_days: "", pack_size: "" },
            ])
          }
        >
          <Plus aria-hidden />
          {t("add")}
        </Button>
        {rows.length > 0 && !rows.some((row) => row.supplier_id === preferred) ? (
          <p className="text-muted-foreground text-xs">{t("firstPreferred")}</p>
        ) : null}
        {error ? (
          <p role="alert" className="text-destructive text-sm font-medium">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          <Button variant="outline" className="min-h-11" onClick={() => setOpen(false)}>
            {t("cancel")}
          </Button>
          <Button className="min-h-11" disabled={busy} onClick={() => void save()}>
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
