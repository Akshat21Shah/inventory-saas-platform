"use client";

import { useQueryClient } from "@tanstack/react-query";
import { MessageCircle, NotebookPen, Phone, RefreshCw, ShoppingCart } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FilterSelect } from "@/components/catalog/controls";
import { useSalespeopleOptions } from "@/components/retailers/options";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { FilterBar } from "@/components/shared/filter-bar";
import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { MoneyText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { SubNav } from "@/components/shared/sub-nav";
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
import { Textarea } from "@/components/ui/textarea";
import {
  getRetailerActivityQueryKey,
  getShopActivityListQueryKey,
  retailerContactCreate,
  shopActivityRefresh,
  useRetailerActivity,
  useShopActivityList,
} from "@/lib/api/generated/endpoints/insights/insights";
import type {
  ShopActivity,
  ShopActivityListSegment,
  ShopContactChannelEnum,
  ShopContactOutcomeEnum,
} from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { formatDate, formatDateTime } from "@/lib/format";
import { useListSearch } from "@/lib/list-search";
import { useDebounced } from "@/lib/use-debounced";
import { useIsCompact } from "@/lib/use-media";
import { formatIndianMobile } from "@/lib/utils";

const ALL = "all";
const SEGMENTS = ["DORMANT", "SLOWING", "NEVER_ORDERED", "NEW", "ACTIVE"] as const;
const CHANNELS: ShopContactChannelEnum[] = ["CALL", "WHATSAPP", "VISIT", "OTHER"];
const OUTCOMES: ShopContactOutcomeEnum[] = [
  "REACHED",
  "NO_ANSWER",
  "WILL_ORDER",
  "NOT_INTERESTED",
  "OTHER",
];

/** The Shops section's tabs: every shop, and their ordering activity (ADR-056 item 3). */
export function RetailersNav() {
  const t = useTranslations("insights.nav");
  return (
    <SubNav
      label={t("label")}
      items={[
        { href: "/manage/retailers", label: t("all") },
        { href: "/manage/retailers/activity", label: t("activity") },
      ]}
    />
  );
}

export function SegmentBadge({ segment }: { segment: string }) {
  return <StatusBadge status={segment} labels="segmentStatus" />;
}

/** "3 days ago", "today" or "never": how long since the last order. */
function Since({ row }: { row: Pick<ShopActivity, "last_order_date" | "days_since_last"> }) {
  const t = useTranslations("insights.list");
  if (!row.last_order_date || row.days_since_last === null) {
    return <span className="text-muted-foreground">{t("never")}</span>;
  }
  return (
    <span className="whitespace-nowrap">
      {formatDate(row.last_order_date)}
      <span className="text-muted-foreground block text-xs">
        {t("daysAgo", { days: row.days_since_last })}
      </span>
    </span>
  );
}

function digits(mobile: string): string {
  return mobile.replace(/\D/g, "");
}

/** Call and WhatsApp from the staff member's own phone (no messages are sent by the platform),
 * a staff order for the shop, and logging what happened. In a list (``compact``) they are icon
 * buttons with their names for screen readers and on hover: a row on laptops, a column at the
 * side of each card on phones and tablets. */
export function ContactActions({
  shop,
  compact = false,
}: {
  shop: Pick<ShopActivity, "retailer_id" | "shop_name" | "owner_name" | "mobile">;
  compact?: boolean;
}) {
  const t = useTranslations("insights.list");
  const { me, can } = useAuth();
  const cards = useIsCompact();
  const icons = compact;
  const message = t("message", {
    name: shop.owner_name || shop.shop_name,
    staff: me?.full_name ?? "",
    business: me?.tenant?.name ?? "",
    shop: shop.shop_name,
  });
  const size = icons ? "icon" : "default";
  const label = (text: string) => (icons ? null : text);
  return (
    <div
      className={icons ? (cards ? "flex flex-col gap-1" : "flex gap-1") : "flex flex-wrap gap-2"}
    >
      {shop.mobile ? (
        <>
          <Button asChild size={size} variant="outline">
            <a
              href={`tel:${shop.mobile}`}
              aria-label={t("callShop", { shop: shop.shop_name })}
              title={t("call")}
            >
              <Phone aria-hidden />
              {label(t("call"))}
            </a>
          </Button>
          <Button asChild size={size} variant="outline">
            <a
              href={`https://wa.me/${digits(shop.mobile)}?text=${encodeURIComponent(message)}`}
              target="_blank"
              rel="noreferrer"
              aria-label={t("whatsappShop", { shop: shop.shop_name })}
              title={t("whatsapp")}
            >
              <MessageCircle aria-hidden />
              {label(t("whatsapp"))}
            </a>
          </Button>
        </>
      ) : null}
      {can("orders.create_on_behalf") ? (
        <Button asChild size={size} variant="outline">
          <Link
            href={`/manage/orders/new?shop=${shop.retailer_id}`}
            aria-label={t("order")}
            title={t("order")}
          >
            <ShoppingCart aria-hidden />
            {label(t("order"))}
          </Link>
        </Button>
      ) : null}
      <LogContactDialog
        shopId={shop.retailer_id}
        shopName={shop.shop_name}
        size={size}
        iconOnly={icons}
      />
    </div>
  );
}

export function LogContactDialog({
  shopId,
  shopName,
  size = "default",
  iconOnly = false,
}: {
  shopId: string;
  shopName: string;
  size?: "sm" | "default" | "icon";
  iconOnly?: boolean;
}) {
  const t = useTranslations("insights.contact");
  const errors = useErrorText();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [channel, setChannel] = useState<ShopContactChannelEnum>("CALL");
  const [outcome, setOutcome] = useState<ShopContactOutcomeEnum>("REACHED");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await retailerContactCreate(shopId, { channel, outcome, note: note.trim() });
      toast.success(t("saved", { shop: shopName }));
      setOpen(false);
      setNote("");
      await Promise.all([
        client.invalidateQueries({ queryKey: getShopActivityListQueryKey() }),
        client.invalidateQueries({ queryKey: getRetailerActivityQueryKey(shopId) }),
        client.invalidateQueries({ queryKey: ["/api/v1/dashboard/"] }),
      ]);
    } catch (err) {
      toast.error(errors.message(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          size={size}
          variant="outline"
          aria-label={iconOnly ? t("open") : undefined}
          title={iconOnly ? t("open") : undefined}
        >
          <NotebookPen aria-hidden />
          {iconOnly ? null : t("open")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title", { shop: shopName })}</DialogTitle>
          <DialogDescription>{t("body")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <FormField label={t("how")}>
            <FormSelect
              value={channel}
              onValueChange={(value) => setChannel(value as ShopContactChannelEnum)}
              options={CHANNELS.map((code) => ({ value: code, label: t(`channels.${code}`) }))}
            />
          </FormField>
          <FormField label={t("outcome")}>
            <FormSelect
              value={outcome}
              onValueChange={(value) => setOutcome(value as ShopContactOutcomeEnum)}
              options={OUTCOMES.map((code) => ({ value: code, label: t(`outcomes.${code}`) }))}
            />
          </FormField>
          <FormField label={t("note")} hint={t("noteHint")}>
            <Textarea value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
          </FormField>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            {t("cancel")}
          </Button>
          <Button onClick={() => void save()} disabled={saving}>
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function LastContact({ row }: { row: ShopActivity }) {
  const t = useTranslations("insights");
  if (!row.last_contact_at) return <span className="text-muted-foreground">—</span>;
  return (
    <span>
      {row.last_contact_outcome ? t(`contact.outcomes.${row.last_contact_outcome}`) : null}
      <span className="text-muted-foreground block text-xs">
        {formatDate(row.last_contact_at)}
        {row.last_contact_by ? ` · ${row.last_contact_by}` : ""}
      </span>
    </span>
  );
}

function Orders({ row }: { row: ShopActivity }) {
  const t = useTranslations("insights.list");
  return (
    <span className="whitespace-nowrap">
      {row.orders_prev_90 > 0
        ? t("ordersWas", { now: row.orders_90, before: row.orders_prev_90 })
        : row.orders_90}
    </span>
  );
}

export function ShopActivityPage() {
  const t = useTranslations("insights.list");
  const tSegment = useTranslations("segmentStatus");
  const errors = useErrorText();
  const client = useQueryClient();
  const salespeople = useSalespeopleOptions();
  const [search, setSearch] = useListSearch();
  const [show, setShow] = useState<"winBack" | "all">("winBack");
  const [segment, setSegment] = useState(ALL);
  const [salesperson, setSalesperson] = useState(ALL);
  const [refreshing, setRefreshing] = useState(false);
  const cursor = useCursor();
  const debounced = useDebounced(search.trim());

  const query = useShopActivityList({
    cursor: cursor.cursor,
    search: debounced || undefined,
    win_back: show === "winBack" ? true : undefined,
    segment: segment === ALL ? undefined : (segment as ShopActivityListSegment),
    salesperson: salesperson === ALL ? undefined : salesperson,
  });
  const page = query.data?.data;
  const rows = page?.results ?? [];
  const values = rows.some((row) => row.value_90 !== null);

  function filtered(setter: (value: string) => void) {
    return (value: string) => {
      setter(value);
      cursor.reset();
    };
  }

  async function refresh() {
    setRefreshing(true);
    try {
      await shopActivityRefresh();
      toast.success(t("refreshing"));
      window.setTimeout(
        () => void client.invalidateQueries({ queryKey: getShopActivityListQueryKey() }),
        5000,
      );
    } catch (err) {
      toast.error(errors.message(err));
    } finally {
      setRefreshing(false);
    }
  }

  // Values only for people who may see sales figures (the server leaves them out otherwise).
  const valueColumn: DataTableColumn<ShopActivity> = {
    id: "value",
    header: t("value"),
    cell: ({ row }) =>
      row.original.value_90 !== null && row.original.orders_90 > 0 ? (
        <MoneyText value={row.original.value_90} />
      ) : (
        "—"
      ),
  };
  const columns: DataTableColumn<ShopActivity>[] = [
    {
      id: "shop",
      header: t("shop"),
      cell: ({ row }) => (
        <Link
          href={`/manage/retailers/${row.original.retailer_id}`}
          className="block hover:underline"
        >
          <span className="block font-medium">{row.original.shop_name}</span>
          <span className="text-muted-foreground block text-xs">
            {[row.original.owner_name, formatIndianMobile(row.original.mobile)]
              .filter(Boolean)
              .join(" · ")}
          </span>
          {row.original.salesperson_name ? (
            <span className="text-muted-foreground block text-xs">
              {t("salespersonIs", { name: row.original.salesperson_name })}
            </span>
          ) : null}
        </Link>
      ),
    },
    {
      id: "segment",
      header: t("segment"),
      cell: ({ row }) => <SegmentBadge segment={row.original.segment} />,
    },
    { id: "lastOrder", header: t("lastOrder"), cell: ({ row }) => <Since row={row.original} /> },
    {
      id: "usually",
      header: t("usually"),
      cell: ({ row }) =>
        row.original.usual_gap_days ? (
          <span className="whitespace-nowrap">
            {t("every", { days: Math.round(Number(row.original.usual_gap_days)) })}
          </span>
        ) : (
          "—"
        ),
    },
    { id: "orders", header: t("orders"), cell: ({ row }) => <Orders row={row.original} /> },
    ...(values ? [valueColumn] : []),
    { id: "contact", header: t("contact"), cell: ({ row }) => <LastContact row={row.original} /> },
    {
      id: "actions",
      header: t("actions"),
      cell: ({ row }) => <ContactActions shop={row.original} compact />,
    },
  ];

  const computedAt = rows[0]?.computed_at;
  const filtering =
    Boolean(debounced) || segment !== ALL || salesperson !== ALL || show === "winBack";
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Button
            variant="outline"
            className="min-h-10"
            onClick={() => void refresh()}
            disabled={refreshing}
          >
            <RefreshCw aria-hidden />
            {t("refresh")}
          </Button>
        }
      />
      <RetailersNav />
      {computedAt ? (
        <p className="text-muted-foreground mb-3 text-sm">
          {t("computed", { when: formatDateTime(computedAt) })}
        </p>
      ) : null}
      <DataTable
        columns={columns}
        data={rows}
        getRowId={(row) => row.retailer_id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        numericColumns={["orders", "value"]}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={
          show === "winBack" && !debounced && segment === ALL && salesperson === ALL
            ? { title: t("emptyWinBackTitle"), description: t("emptyWinBackBody") }
            : filtering
              ? { title: t("noMatchTitle"), description: t("noMatchBody") }
              : { title: t("emptyTitle"), description: t("emptyBody") }
        }
        cardLayout={{
          shop: "title",
          segment: "primary",
          lastOrder: "primary",
          orders: "primary",
          usually: "secondary",
          value: "secondary",
          contact: "secondary",
          actions: "actions",
        }}
        toolbar={
          <FilterBar
            active={[segment, salesperson].filter((f) => f !== ALL).length}
            onClear={() => {
              setSegment(ALL);
              setSalesperson(ALL);
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
                  label={t("show")}
                  value={show}
                  onChange={filtered((value) => setShow(value === "all" ? "all" : "winBack"))}
                  options={[
                    { value: "winBack", label: t("winBack") },
                    { value: "all", label: t("everyone") },
                  ]}
                />
                <FilterSelect
                  label={t("segment")}
                  value={segment}
                  onChange={filtered(setSegment)}
                  options={[
                    { value: ALL, label: t("anySegment") },
                    ...SEGMENTS.map((code) => ({ value: code, label: tSegment(code) })),
                  ]}
                />
                {salespeople.length ? (
                  <FilterSelect
                    label={t("salesperson")}
                    value={salesperson}
                    onChange={filtered(setSalesperson)}
                    options={[{ value: ALL, label: t("anySalesperson") }, ...salespeople]}
                  />
                ) : null}
              </>
            }
          />
        }
      />
    </>
  );
}

/** A shop's ordering activity and the contacts logged with it, on the shop's page. */
export function ShopActivityCard({ retailerId }: { retailerId: string }) {
  const t = useTranslations("insights.card");
  const tList = useTranslations("insights.list");
  const tContact = useTranslations("insights.contact");
  const query = useRetailerActivity(retailerId);
  if (query.isLoading) return <CardSkeleton />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const data = query.data?.data;
  if (!data) return null;
  const activity = data.activity;
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle className="text-base">{t("title")}</CardTitle>
        {activity ? <SegmentBadge segment={activity.segment} /> : null}
      </CardHeader>
      <CardContent className="space-y-4">
        {activity ? (
          <>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-muted-foreground">{tList("lastOrder")}</dt>
                <dd>
                  <Since row={activity} />
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{tList("usually")}</dt>
                <dd>
                  {activity.usual_gap_days
                    ? tList("every", { days: Math.round(Number(activity.usual_gap_days)) })
                    : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{tList("orders")}</dt>
                <dd>
                  <Orders row={activity} />
                </dd>
              </div>
              {activity.value_90 !== null ? (
                <div>
                  <dt className="text-muted-foreground">{tList("value")}</dt>
                  <dd>{activity.orders_90 > 0 ? <MoneyText value={activity.value_90} /> : "—"}</dd>
                </div>
              ) : null}
            </dl>
            <ContactActions shop={activity} />
          </>
        ) : (
          <p className="text-muted-foreground text-sm">{t("notYet")}</p>
        )}
        <section aria-labelledby={`contacts-${retailerId}`} className="space-y-2">
          <h3 id={`contacts-${retailerId}`} className="text-sm font-semibold">
            {t("contacts")}
          </h3>
          {data.contacts.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("noContacts")}</p>
          ) : (
            <ul className="divide-y rounded-md border">
              {data.contacts.map((contact) => (
                <li key={contact.id} className="space-y-0.5 p-3 text-sm">
                  <p className="font-medium">
                    {tContact(`channels.${contact.channel}`)} ·{" "}
                    {tContact(`outcomes.${contact.outcome}`)}
                  </p>
                  {contact.note ? <p>{contact.note}</p> : null}
                  <p className="text-muted-foreground text-xs">
                    {t("by", { by: contact.by_name, when: formatDateTime(contact.created_at) })}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </CardContent>
    </Card>
  );
}
