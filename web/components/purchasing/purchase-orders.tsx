"use client";

import { ArrowLeft, FileDown, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { FormActions } from "@/components/shared/form-actions";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { DateText, MoneyText, QtyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { ScanBar } from "@/components/stock/scan-bar";
import { UnitChoice, unitLabel, type Product } from "@/components/stock/receipt-editor";
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
import { Textarea } from "@/components/ui/textarea";
import {
  purchaseOrdersCancel,
  purchaseOrdersClose,
  purchaseOrdersCreate,
  purchaseOrdersDelete,
  purchaseOrdersPdf,
  purchaseOrdersReceive,
  purchaseOrdersSend,
  purchaseOrdersUpdate,
  usePurchaseOrdersGet,
  usePurchaseOrdersList,
} from "@/lib/api/generated/endpoints/purchasing/purchasing";
import type {
  EnteredUnitEnum,
  PurchaseOrderDetail,
  PurchaseOrderLine,
  PurchaseOrderList,
  PurchaseOrderStatusEnum,
  SendResult,
} from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { idempotent, newIdempotencyKey } from "@/lib/idempotency";
import { initialQuery } from "@/lib/initial-query";
import { useDebounced } from "@/lib/use-debounced";
import { useIsCompact } from "@/lib/use-media";

import { useSupplierOptions } from "./options";

const ALL = "all";
const STATUSES: PurchaseOrderStatusEnum[] = [
  "DRAFT",
  "SENT",
  "PARTLY_RECEIVED",
  "RECEIVED",
  "CLOSED",
  "CANCELLED",
];

function Back({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="text-muted-foreground hover:text-foreground mb-2 inline-flex min-h-11 items-center gap-1 text-sm"
    >
      <ArrowLeft aria-hidden className="size-4" />
      {label}
    </Link>
  );
}

function LateBadge() {
  const t = useTranslations("purchasing.orders");
  return (
    <Badge variant="destructive" className="ml-1">
      {t("late")}
    </Badge>
  );
}

export function PurchaseOrdersPage() {
  const t = useTranslations("purchasing.orders");
  const { can } = useAuth();
  const suppliers = useSupplierOptions();
  const [search, setSearch] = useState(initialQuery);
  const [status, setStatus] = useState(ALL);
  const [supplier, setSupplier] = useState(ALL);
  const [late, setLate] = useState(ALL);
  const cursor = useCursor();
  const debounced = useDebounced(search.trim());
  const query = usePurchaseOrdersList({
    cursor: cursor.cursor,
    search: debounced || undefined,
    status: status === ALL ? undefined : (status as PurchaseOrderStatusEnum),
    supplier: supplier === ALL ? undefined : supplier,
    late: late === ALL ? undefined : true,
  });
  const page = query.data?.data;
  const rows = page?.results ?? [];
  const costs = can("costs.view");
  const filtered = (setter: (value: string) => void) => (value: string) => {
    setter(value);
    cursor.reset();
  };

  const columns: DataTableColumn<PurchaseOrderList>[] = [
    {
      id: "number",
      header: t("number"),
      cell: ({ row }) => (
        <Link
          href={`/manage/purchasing/orders/${row.original.id}`}
          className="block hover:underline"
        >
          <span className="block font-medium">{row.original.number}</span>
          <span className="text-muted-foreground block text-xs">{row.original.supplier_name}</span>
        </Link>
      ),
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => (
        <span className="inline-flex flex-wrap items-center gap-1">
          <StatusBadge status={row.original.status} labels="purchaseOrderStatus" />
          {row.original.changed_since_sent ? (
            <Badge variant="outline">{t("changedSinceSent")}</Badge>
          ) : null}
        </span>
      ),
    },
    {
      id: "expected",
      header: t("expected"),
      cell: ({ row }) =>
        row.original.expected_date ? (
          <span className="whitespace-nowrap">
            <DateText value={row.original.expected_date} />
            {row.original.is_late ? <LateBadge /> : null}
          </span>
        ) : (
          "—"
        ),
    },
    {
      id: "lines",
      header: t("lines"),
      cell: ({ row }) => <span className="tabular-nums">{row.original.line_count}</span>,
    },
    ...(costs
      ? [
          {
            id: "value",
            header: t("value"),
            cell: ({ row }: { row: { original: PurchaseOrderList } }) =>
              row.original.subtotal ? <MoneyText value={row.original.subtotal} /> : "—",
          } satisfies DataTableColumn<PurchaseOrderList>,
        ]
      : []),
    {
      id: "sent",
      header: t("sent"),
      cell: ({ row }) =>
        row.original.sent_at ? <DateText value={row.original.sent_at} /> : t("notSent"),
    },
  ];
  const active = [status, supplier, late].filter((f) => f !== ALL).length;
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          can("purchasing.manage") ? (
            <Button asChild className="min-h-10">
              <Link href="/manage/purchasing/orders/new">
                <Plus aria-hidden />
                {t("new")}
              </Link>
            </Button>
          ) : null
        }
      />
      <DataTable
        columns={columns}
        data={rows}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["lines", "value"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={
          debounced || active
            ? { title: t("noMatchTitle"), description: t("noMatchBody") }
            : { title: t("emptyTitle"), description: t("emptyBody") }
        }
        cardLayout={{
          number: "title",
          status: "primary",
          expected: "primary",
          value: "primary",
          lines: "secondary",
          sent: "secondary",
        }}
        toolbar={
          <FilterBar
            active={active}
            onClear={() => {
              for (const reset of [setStatus, setSupplier, setLate]) reset(ALL);
              cursor.reset();
            }}
            search={
              <Input
                type="search"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  cursor.reset();
                }}
                placeholder={t("searchPlaceholder")}
                aria-label={t("search")}
                className="h-10 w-full sm:w-64"
              />
            }
            filters={
              <>
                <FilterSelect
                  label={t("status")}
                  value={status}
                  onChange={filtered(setStatus)}
                  options={[
                    { value: ALL, label: t("anyStatus") },
                    ...STATUSES.map((s) => ({ value: s, label: t(`statuses.${s}`) })),
                  ]}
                />
                <FilterSelect
                  label={t("supplier")}
                  value={supplier}
                  onChange={filtered(setSupplier)}
                  options={[{ value: ALL, label: t("anySupplier") }, ...suppliers]}
                />
                <FilterSelect
                  label={t("arrival")}
                  value={late}
                  onChange={filtered(setLate)}
                  options={[
                    { value: ALL, label: t("anyArrival") },
                    { value: "late", label: t("onlyLate") },
                  ]}
                />
              </>
            }
          />
        }
      />
    </>
  );
}

// --- Editing ----------------------------------------------------------------------------------

interface Line {
  key: string;
  id?: string;
  product: Product;
  unit: EnteredUnitEnum;
  qty: string;
  cost: string;
}

let counter = 0;
const lineKey = () => `po-line-${++counter}`;

function fromOrder(line: PurchaseOrderLine): Line {
  return {
    key: lineKey(),
    id: line.id,
    product: {
      id: line.product_id,
      code: line.product_code,
      name: line.product_name,
      unit: { code: line.unit_code } as Product["unit"],
      pack_unit: line.pack_unit_code ? ({ code: line.pack_unit_code } as Product["unit"]) : null,
      pack_size: line.pack_size,
    },
    unit: line.entered_unit,
    qty: String(Number(line.entered_qty)),
    cost: line.entered_cost ? String(Number(line.entered_cost)) : "",
  };
}

export function PurchaseOrderEditor({ order }: { order?: PurchaseOrderDetail }) {
  const t = useTranslations("purchasing.editor");
  const errors = useErrorText();
  const router = useRouter();
  const params = useSearchParams();
  // Lines stack below 1024 px: a tablet beside the menu has no room for one row.
  const compact = useIsCompact();
  const { can } = useAuth();
  const costs = can("costs.view");
  const suppliers = useSupplierOptions();
  const [supplierId, setSupplierId] = useState(order?.supplier_id ?? params.get("supplier") ?? "");
  const [expected, setExpected] = useState(order?.expected_date ?? "");
  const [notes, setNotes] = useState(order?.notes ?? "");
  const [lines, setLines] = useState<Line[]>(() => order?.lines.map(fromOrder) ?? []);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const scanRef = useRef<HTMLInputElement>(null);
  const sent = Boolean(order && order.status !== "DRAFT");

  function add(product: Product) {
    if (lines.some((line) => line.product.id === product.id)) {
      toast.message(t("already", { name: product.name }));
      return;
    }
    setLines((current) => [
      ...current,
      { key: lineKey(), product, unit: "BASE", qty: "1", cost: "" },
    ]);
  }
  function update(key: string, change: Partial<Line>) {
    setLines((current) => current.map((l) => (l.key === key ? { ...l, ...change } : l)));
  }

  const remove = (line: Line) => (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-11 shrink-0 md:size-9"
      aria-label={t("remove", { name: line.product.name })}
      onClick={() => setLines((c) => c.filter((l) => l.key !== line.key))}
    >
      <Trash2 aria-hidden />
    </Button>
  );

  async function save() {
    if (!supplierId) {
      setFieldErrors({ supplier_id: t("chooseSupplier") });
      return;
    }
    if (!lines.length) {
      toast.error(t("noLines"));
      return;
    }
    setSaving(true);
    setFieldErrors({});
    const body = {
      supplier_id: supplierId,
      expected_date: expected || null,
      notes,
      lines: lines.map((line) => ({
        ...(line.id ? { id: line.id } : {}),
        product_id: line.product.id,
        entered_unit: line.unit,
        entered_qty: line.qty.trim() || "0",
        ...(costs ? { entered_cost: line.cost.trim() || null } : {}),
      })),
    };
    try {
      const response = order
        ? await purchaseOrdersUpdate(order.id, body)
        : await purchaseOrdersCreate(body);
      toast.success(order ? t("saved") : t("created"));
      router.replace(`/manage/purchasing/orders/${response.data.id}`);
    } catch (err) {
      const fields = errors.fields(err);
      setFieldErrors(fields);
      toast.error(Object.keys(fields).length ? t("fix") : errors.message(err));
    } finally {
      setSaving(false);
    }
  }

  const lineError = (index: number) => fieldErrors[`lines.${index + 1}`];
  return (
    <>
      <Back
        href={order ? `/manage/purchasing/orders/${order.id}` : "/manage/purchasing/orders"}
        label={order ? order.number : t("allOrders")}
      />
      <PageHeader
        title={order ? t("editTitle", { number: order.number }) : t("newTitle")}
        description={sent ? t("sentNote") : t("newBody")}
      />
      <div className="space-y-6">
        <Card>
          <CardContent className="grid gap-4 py-5 sm:grid-cols-2 lg:grid-cols-3">
            <FormField label={t("supplier")} error={fieldErrors.supplier_id} required>
              <FormSelect
                value={supplierId}
                onValueChange={setSupplierId}
                options={suppliers}
                placeholder={t("chooseSupplier")}
                disabled={sent}
              />
            </FormField>
            <FormField
              label={t("expected")}
              error={fieldErrors.expected_date}
              hint={t("expectedHint")}
            >
              <Input
                type="date"
                value={expected}
                onChange={(e) => setExpected(e.target.value)}
                className="h-11"
              />
            </FormField>
            <FormField
              label={t("notes")}
              hint={t("notesHint")}
              className="sm:col-span-2 lg:col-span-1"
            >
              <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
            </FormField>
          </CardContent>
        </Card>
        <section aria-labelledby="po-lines" className="space-y-3">
          <h2 id="po-lines" className="text-lg font-semibold">
            {t("linesTitle", { count: lines.length })}
          </h2>
          <ScanBar onPick={add} inputRef={scanRef} />
          {fieldErrors.lines ? (
            <p role="alert" className="text-destructive text-sm">
              {fieldErrors.lines}
            </p>
          ) : null}
          {!costs ? <p className="text-muted-foreground text-sm">{t("noCostNote")}</p> : null}
          {lines.length === 0 ? (
            <p className="text-muted-foreground rounded-lg border border-dashed px-4 py-8 text-center text-sm">
              {t("emptyLines")}
            </p>
          ) : (
            <ul className="space-y-3">
              {lines.map((line, index) => (
                <li key={line.key}>
                  <Card className={lineError(index) ? "border-destructive" : undefined}>
                    <CardContent
                      className={
                        compact
                          ? "space-y-3 py-4"
                          : "grid grid-cols-[1fr_auto_8rem_10rem_auto] items-end gap-3 py-3"
                      }
                    >
                      <div className="flex items-start justify-between gap-2 self-center">
                        <div className="min-w-0">
                          <p className="font-medium">{line.product.name}</p>
                          <p className="text-muted-foreground text-xs">{line.product.code}</p>
                          {lineError(index) ? (
                            <p role="alert" className="text-destructive mt-1 text-xs">
                              {lineError(index)}
                            </p>
                          ) : null}
                        </div>
                        {compact ? remove(line) : null}
                      </div>
                      <UnitChoice line={line} onChange={(unit) => update(line.key, { unit })} />
                      <div className={compact ? "grid grid-cols-2 gap-3" : "contents"}>
                        <label className="space-y-1">
                          <span className="text-muted-foreground block text-xs">
                            {t("qtyLabel")}
                          </span>
                          <Input
                            inputMode="decimal"
                            value={line.qty}
                            onChange={(e) => update(line.key, { qty: e.target.value })}
                            aria-label={t("qtyFor", {
                              name: line.product.name,
                              unit: unitLabel(line.product, line.unit),
                            })}
                            className="h-11 text-right tabular-nums md:h-9"
                          />
                        </label>
                        {costs ? (
                          <label className="space-y-1">
                            <span className="text-muted-foreground block text-xs">
                              {t("costLabel")}
                            </span>
                            <Input
                              inputMode="decimal"
                              value={line.cost}
                              onChange={(e) => update(line.key, { cost: e.target.value })}
                              aria-label={t("costFor", {
                                name: line.product.name,
                                unit: unitLabel(line.product, line.unit),
                              })}
                              placeholder={t("usualCost")}
                              className="h-11 text-right tabular-nums md:h-9"
                            />
                          </label>
                        ) : null}
                      </div>
                      {compact ? null : remove(line)}
                    </CardContent>
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </section>
        <FormActions>
          <Button asChild variant="outline" className="min-h-11">
            <Link
              href={order ? `/manage/purchasing/orders/${order.id}` : "/manage/purchasing/orders"}
            >
              {t("cancel")}
            </Link>
          </Button>
          <Button className="min-h-11" disabled={saving} onClick={() => void save()}>
            {order ? t("save") : t("create")}
          </Button>
        </FormActions>
      </div>
    </>
  );
}

export function EditPurchaseOrderPage({ orderId }: { orderId: string }) {
  const query = usePurchaseOrdersGet(orderId);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  return <PurchaseOrderEditor order={query.data.data} />;
}

// --- One purchase order --------------------------------------------------------------------

export function PurchaseOrderPage({ orderId }: { orderId: string }) {
  const t = useTranslations("purchasing.order");
  const ts = useTranslations("purchasing.orders");
  const errors = useErrorText();
  const router = useRouter();
  const { can } = useAuth();
  const query = usePurchaseOrdersGet(orderId);
  const [sent, setSent] = useState<SendResult | null>(null);
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  const order = query.data.data;
  const actions = new Set(order.actions);
  const manage = can("purchasing.manage");
  const costs = can("costs.view");
  const refresh = () => void query.refetch();

  async function run(work: () => Promise<unknown>, done: string) {
    try {
      await work();
      toast.success(done);
      refresh();
    } catch (err) {
      const fields = errors.fields(err);
      toast.error(fields.reason ?? errors.message(err));
      throw err;
    }
  }

  async function pdf() {
    try {
      const response = await purchaseOrdersPdf(order.id);
      if (response.data.url) window.open(response.data.url, "_blank", "noopener");
      else toast.message(t("pdfPreparing"));
    } catch (err) {
      toast.error(errors.message(err));
    }
  }

  async function receive() {
    try {
      const response = await purchaseOrdersReceive(order.id);
      router.push(`/manage/stock/inwards/${response.data.id}`);
    } catch (err) {
      toast.error(errors.message(err));
    }
  }

  const columns: DataTableColumn<PurchaseOrderLine>[] = [
    {
      id: "product",
      header: t("product"),
      cell: ({ row }) => (
        <Link
          href={`/manage/products/${row.original.product_id}`}
          className="block hover:underline"
        >
          <span className="block font-medium">{row.original.product_name}</span>
          <span className="text-muted-foreground block text-xs">
            {row.original.product_code}
            {row.original.supplier_code
              ? ` · ${t("theirCode", { code: row.original.supplier_code })}`
              : ""}
          </span>
        </Link>
      ),
    },
    {
      id: "ordered",
      header: t("ordered"),
      cell: ({ row }) => (
        <span className="whitespace-nowrap">
          <QtyText value={row.original.quantity} /> {row.original.unit_code}
        </span>
      ),
    },
    {
      id: "received",
      header: t("received"),
      cell: ({ row }) => <QtyText value={row.original.qty_received} />,
    },
    {
      id: "due",
      header: t("due"),
      cell: ({ row }) =>
        Number(row.original.qty_cancelled) ? (
          <span className="whitespace-nowrap">
            <QtyText value={row.original.due} />{" "}
            <span className="text-muted-foreground text-xs">
              ({t("cancelledQty")} <QtyText value={row.original.qty_cancelled} />)
            </span>
          </span>
        ) : (
          <QtyText value={row.original.due} />
        ),
    },
    ...(costs
      ? [
          {
            id: "rate",
            header: t("rate"),
            cell: ({ row }: { row: { original: PurchaseOrderLine } }) =>
              row.original.unit_cost ? <MoneyText value={row.original.unit_cost} /> : "—",
          } satisfies DataTableColumn<PurchaseOrderLine>,
          {
            id: "amount",
            header: t("amount"),
            cell: ({ row }: { row: { original: PurchaseOrderLine } }) =>
              row.original.line_total ? <MoneyText value={row.original.line_total} /> : "—",
          } satisfies DataTableColumn<PurchaseOrderLine>,
        ]
      : []),
  ];

  return (
    <>
      <Back href="/manage/purchasing/orders" label={ts("title")} />
      <PageHeader
        title={order.number}
        description={order.supplier_name}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" className="min-h-10" onClick={() => void pdf()}>
              <FileDown aria-hidden />
              {costs ? t("pdf") : t("pdfNoPrices")}
            </Button>
            {manage && actions.has("edit") ? (
              <Button asChild variant="outline" className="min-h-10">
                <Link href={`/manage/purchasing/orders/${order.id}/edit`}>{t("edit")}</Link>
              </Button>
            ) : null}
            {can("stock.inward") && actions.has("receive") ? (
              <Button variant="outline" className="min-h-10" onClick={() => void receive()}>
                {t("receive")}
              </Button>
            ) : null}
            {manage && actions.has("send") ? (
              <SendDialog
                order={order}
                onSent={(result) => {
                  setSent(result);
                  refresh();
                }}
              />
            ) : null}
            {manage && actions.has("cancel") ? (
              <CancelDialog order={order} onDone={refresh} />
            ) : null}
            {manage && actions.has("close") ? (
              <ReasonDialog
                trigger={
                  <Button variant="outline" className="min-h-10">
                    {t("close")}
                  </Button>
                }
                title={t("closeTitle", { number: order.number })}
                description={t("closeBody")}
                reasonLabel={t("reason")}
                confirmLabel={t("close")}
                destructive
                onConfirm={(reason) =>
                  run(() => purchaseOrdersClose(order.id, { reason }), t("closed"))
                }
              />
            ) : null}
            {manage && actions.has("delete") ? (
              <ConfirmDialog
                destructive
                trigger={
                  <Button variant="outline" className="min-h-10">
                    {t("delete")}
                  </Button>
                }
                title={t("deleteTitle", { number: order.number })}
                confirmLabel={t("delete")}
                onConfirm={async () => {
                  try {
                    await purchaseOrdersDelete(order.id);
                    toast.success(t("deleted"));
                    router.replace("/manage/purchasing/orders");
                  } catch (err) {
                    toast.error(errors.message(err));
                  }
                }}
              />
            ) : null}
          </div>
        }
      />
      {sent ? <SharePanel result={sent} onClose={() => setSent(null)} /> : null}
      <div className="grid gap-6 xl:grid-cols-[1fr_22rem]">
        <DataTable
          columns={columns}
          data={[...order.lines]}
          getRowId={(row) => row.id}
          numericColumns={["ordered", "received", "due", "rate", "amount"]}
          caption={t("lines")}
          empty={{ title: t("noLines"), description: "" }}
          cardLayout={{
            product: "title",
            ordered: "primary",
            received: "primary",
            due: "primary",
            rate: "secondary",
            amount: "secondary",
          }}
        />
        {/* The summary first on phones and tablets, beside the lines on laptops. */}
        <div className="space-y-6 max-xl:order-first">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("summary")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Fact label={t("status")}>
                <span className="inline-flex flex-wrap items-center justify-end gap-1">
                  <StatusBadge status={order.status} labels="purchaseOrderStatus" />
                  {order.revision > 1 ? (
                    <Badge variant="outline">{t("revision", { n: order.revision })}</Badge>
                  ) : null}
                  {order.changed_since_sent ? (
                    <Badge variant="outline">{ts("changedSinceSent")}</Badge>
                  ) : null}
                </span>
              </Fact>
              <Fact label={t("supplier")}>
                <Link
                  href={`/manage/purchasing/suppliers/${order.supplier_id}`}
                  className="hover:underline"
                >
                  {order.supplier_name}
                </Link>
              </Fact>
              <Fact label={t("expected")}>
                {order.expected_date ? (
                  <>
                    <DateText value={order.expected_date} />
                    {order.is_late ? <LateBadge /> : null}
                  </>
                ) : (
                  "—"
                )}
              </Fact>
              <Fact label={t("sent")}>
                {order.sent_at ? (
                  <>
                    <DateText value={order.sent_at} withTime />
                    {order.sent_by ? ` · ${order.sent_by}` : ""}
                  </>
                ) : (
                  ts("notSent")
                )}
              </Fact>
              {costs ? (
                <>
                  <Fact label={t("subtotal")}>
                    <MoneyText value={order.subtotal ?? "0"} />
                  </Fact>
                  <Fact label={t("estimatedTax")}>
                    <MoneyText value={order.estimated_tax ?? "0"} />
                  </Fact>
                  <p className="text-muted-foreground text-xs">{t("taxNote")}</p>
                </>
              ) : null}
              {order.closed_reason ? <Fact label={t("reason")}>{order.closed_reason}</Fact> : null}
              {order.notes ? (
                <div>
                  <p className="text-muted-foreground">{t("notes")}</p>
                  <p className="whitespace-pre-line">{order.notes}</p>
                </div>
              ) : null}
            </CardContent>
          </Card>
          {order.receipts.length ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t("receipts")}</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2 text-sm">
                  {order.receipts.map((r) => (
                    <li key={r.id} className="flex items-center justify-between gap-2">
                      <Link
                        href={`/manage/stock/inwards/${r.id}`}
                        className="font-medium hover:underline"
                      >
                        {r.number ?? t("receiptDraft")}
                      </Link>
                      {r.posted_at ? (
                        <DateText value={r.posted_at} />
                      ) : (
                        <StatusBadge status={r.status} />
                      )}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <p className="flex justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </p>
  );
}

function SendDialog({
  order,
  onSent,
}: {
  order: PurchaseOrderDetail;
  onSent: (result: SendResult) => void;
}) {
  const t = useTranslations("purchasing.order");
  const errors = useErrorText();
  const key = useRef(newIdempotencyKey());
  const email =
    order.supplier_snapshot && typeof order.supplier_snapshot === "object"
      ? (order.supplier_snapshot as { email?: string }).email
      : undefined;
  const again = order.status === "SENT" && !order.changed_since_sent;
  return (
    <ConfirmDialog
      trigger={<Button className="min-h-10">{again ? t("sendAgain") : t("send")}</Button>}
      title={
        order.changed_since_sent
          ? t("sendRevisedTitle", { number: order.number })
          : t("sendTitle", { number: order.number })
      }
      description={email ? t("sendBodyEmail", { email }) : t("sendBody")}
      confirmLabel={t("send")}
      onConfirm={async () => {
        try {
          const response = await purchaseOrdersSend(order.id, idempotent(key.current));
          key.current = newIdempotencyKey();
          toast.success(response.data.emailed ? t("emailed") : t("sentNoEmail"));
          onSent(response.data);
        } catch (err) {
          toast.error(errors.message(err));
        }
      }}
    />
  );
}

function SharePanel({ result, onClose }: { result: SendResult; onClose: () => void }) {
  const t = useTranslations("purchasing.order");
  const text = t("shareText", { number: result.order.number, link: result.share_link });
  return (
    <Card className="border-brand-200 bg-brand-50 mb-6">
      <CardContent className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
        <p className="flex-1 text-sm">{result.emailed ? t("emailedShare") : t("noEmailShare")}</p>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" className="min-h-10">
            <a
              href={`https://wa.me/?text=${encodeURIComponent(text)}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("whatsapp")}
            </a>
          </Button>
          <Button
            variant="outline"
            className="min-h-10"
            onClick={() =>
              void navigator.clipboard
                .writeText(result.share_link)
                .then(() => toast.success(t("copied")))
                .catch(() => toast.error(t("copyFailed")))
            }
          >
            {t("copyLink")}
          </Button>
          <Button variant="ghost" className="min-h-10" onClick={onClose}>
            {t("dismiss")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function CancelDialog({ order, onDone }: { order: PurchaseOrderDetail; onDone: () => void }) {
  const t = useTranslations("purchasing.order");
  const errors = useErrorText();
  const sent = order.status === "SENT";
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [notify, setNotify] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setReason("");
          setNotify(true);
          setError(null);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" className="min-h-10">
          {t("cancel")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("cancelTitle", { number: order.number })}</DialogTitle>
          <DialogDescription>{sent ? t("cancelBodySent") : t("cancelBodyDraft")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="cancel-reason">
            {t("reason")}
            {sent ? " *" : ""}
          </Label>
          <Textarea
            id="cancel-reason"
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>
        {sent ? (
          <label className="flex min-h-11 items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4"
              checked={notify}
              onChange={(e) => setNotify(e.target.checked)}
            />
            {t("emailSupplier")}
          </label>
        ) : null}
        {error ? (
          <p role="alert" className="text-destructive text-sm font-medium">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          <Button variant="outline" className="min-h-11" onClick={() => setOpen(false)}>
            {t("keep")}
          </Button>
          <Button
            variant="destructive"
            className="min-h-11"
            disabled={busy || (sent && !reason.trim())}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await purchaseOrdersCancel(order.id, { reason, notify_supplier: notify });
                toast.success(sent && notify ? t("cancelledEmailed") : t("cancelled"));
                setOpen(false);
                onDone();
              } catch (err) {
                setError(errors.fields(err).reason ?? errors.message(err));
              } finally {
                setBusy(false);
              }
            }}
          >
            {t("cancelOrder")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
