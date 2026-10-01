"use client";

import {
  Building2,
  ClipboardList,
  Clock,
  FileMinus,
  FileText,
  LayoutGrid,
  Package,
  PackagePlus,
  Search,
  Settings,
  ShoppingCart,
  SlidersHorizontal,
  Store,
  Truck,
  Undo2,
  UserRound,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useMessages, useTranslations } from "next-intl";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { DateText, MoneyText } from "@/components/shared/money-text";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  usePlatformSearch,
  usePlatformSearchUsers,
} from "@/lib/api/generated/endpoints/platform/platform";
import { useSearch } from "@/lib/api/generated/endpoints/search/search";
import type { SearchHit, SearchResults, UserHit } from "@/lib/api/generated/model";
import { recentSearches, rememberSearch } from "@/lib/recent-searches";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";

import { PLATFORM_PAGES, SETTING_PAGES, STAFF_PAGES, matches, type Destination } from "./pages";

export type SearchScope = "staff" | "platform";

const noSubscription = () => () => undefined;

const MIN_LENGTH = 2;
const PAGE_LIMIT = 5;

const ICONS: Record<string, LucideIcon> = {
  product: Package,
  shop: Store,
  order: ClipboardList,
  invoice: FileText,
  credit_note: FileMinus,
  payment: Wallet,
  refund: Undo2,
  goods_receipt: PackagePlus,
  adjustment: SlidersHorizontal,
  staff: UserRound,
  supplier: Truck,
  purchase_order: ShoppingCart,
  tenant: Building2,
  page: LayoutGrid,
  setting: Settings,
  recent: Clock,
  people: Users,
};

/** Where a record opens. */
const RECORD_PAGES: Record<string, (id: string) => string> = {
  product: (id) => `/manage/products/${id}`,
  shop: (id) => `/manage/retailers/${id}`,
  order: (id) => `/manage/orders/${id}`,
  invoice: (id) => `/manage/invoices/${id}`,
  credit_note: (id) => `/manage/invoices/credit-notes/${id}`,
  payment: (id) => `/manage/payments/${id}`,
  refund: (id) => `/manage/payments/refunds/${id}`,
  goods_receipt: (id) => `/manage/stock/inwards/${id}`,
  adjustment: (id) => `/manage/stock/adjustments/${id}`,
  staff: () => "/manage/settings/staff",
  supplier: (id) => `/manage/purchasing/suppliers/${id}`,
  purchase_order: (id) => `/manage/purchasing/orders/${id}`,
  tenant: (id) => `/platform/tenants/${id}`,
};

/** "See all": the kind's own list, opened with the same search (`?q=`). */
const LISTS: Partial<Record<string, string>> = {
  product: "/manage/products",
  shop: "/manage/retailers",
  order: "/manage/orders",
  invoice: "/manage/invoices",
  credit_note: "/manage/invoices/credit-notes",
  payment: "/manage/payments",
  supplier: "/manage/purchasing/suppliers",
  purchase_order: "/manage/purchasing/orders",
  tenant: "/platform/tenants",
};

/** Statuses worth a word next to a result (the rest are shown on the record's page). */
const NOTED = new Set([
  "INACTIVE",
  "BLOCKED",
  "DRAFT",
  "CANCELLED",
  "REVERSED",
  "BOUNCED",
  "REJECTED",
]);

interface Option {
  id: string;
  kind: string; // a record type, "page", "setting", "recent", "people", "more"
  title: string;
  detail?: string;
  href?: string;
  hit?: SearchHit;
  person?: UserHit;
  /** What choosing it does instead of opening a page (a recent search, finding people). */
  run?: () => void;
}

interface SearchContextValue {
  open: () => void;
}

const SearchContext = createContext<SearchContextValue | null>(null);

function useSearchDialog(): SearchContextValue {
  const value = useContext(SearchContext);
  if (!value) throw new Error("Search triggers go inside <GlobalSearchProvider>");
  return value;
}

/** Global search for an area (ADR-053): one dialog, opened by the triggers or Ctrl/Cmd + K. */
export function GlobalSearchProvider({
  scope,
  children,
}: {
  scope: SearchScope;
  children: ReactNode;
}) {
  const [isOpen, setOpen] = useState(false);
  useEffect(() => {
    function onKey(event: globalThis.KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const value = useMemo(() => ({ open: () => setOpen(true) }), []);
  return (
    <SearchContext.Provider value={value}>
      {children}
      <Dialog open={isOpen} onOpenChange={setOpen}>
        {isOpen ? <SearchDialog scope={scope} onClose={() => setOpen(false)} /> : null}
      </Dialog>
    </SearchContext.Provider>
  );
}

/** Laptops: a search field in the sidebar, with its shortcut. */
export function SearchField() {
  const t = useTranslations("search");
  const { open } = useSearchDialog();
  const mac = useSyncExternalStore(
    noSubscription,
    () => /Mac|iPhone|iPad/.test(navigator.userAgent),
    () => false,
  );
  return (
    <button
      type="button"
      onClick={open}
      className="text-muted-foreground hover:bg-muted bg-background flex min-h-9 w-full items-center gap-2 rounded-lg border px-3 text-sm"
    >
      <Search aria-hidden className="size-4" />
      <span className="flex-1 text-left">{t("placeholder")}</span>
      <kbd className="bg-muted rounded px-1.5 font-sans text-xs">
        {t("shortcut", { mac: String(mac) })}
      </kbd>
    </button>
  );
}

/** Phones: a search icon in the header; the search fills the screen. */
export function SearchIconButton() {
  const t = useTranslations("search");
  const { open } = useSearchDialog();
  return (
    <Button variant="ghost" size="icon" aria-label={t("open")} onClick={open} className="size-11">
      <Search aria-hidden />
    </Button>
  );
}

function SearchDialog({ scope, onClose }: { scope: SearchScope; onClose: () => void }) {
  const t = useTranslations("search");
  const messages = useMessages();
  const router = useRouter();
  const { me, can, feature } = useAuth();
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [active, setActive] = useState(0);
  const [recent, setRecent] = useState<string[]>(() => recentSearches(me?.id));
  const [people, setPeople] = useState("");
  const query = useDebounced(text.trim(), 250);
  const ready = query.length >= MIN_LENGTH;

  const staff = useSearch({ q: query }, { query: { enabled: scope === "staff" && ready } });
  const platform = usePlatformSearch(
    { q: query },
    { query: { enabled: scope === "platform" && ready } },
  );
  // People across distributors only when asked for: each search is audited on the server.
  const peopleQuery = usePlatformSearchUsers(
    { q: people },
    { query: { enabled: scope === "platform" && people.length >= MIN_LENGTH } },
  );
  const records = scope === "staff" ? staff : platform;
  const results: SearchResults | undefined = records.data?.data;

  const allowed = useCallback(
    (d: Destination) =>
      (!d.feature || feature(d.feature)) &&
      (!d.permission ||
        (Array.isArray(d.permission) ? d.permission.some((p) => can(p)) : can(d.permission))),
    [can, feature],
  );

  const pages = useMemo((): Option[] => {
    if (!ready) return [];
    const list = scope === "staff" ? STAFF_PAGES : PLATFORM_PAGES;
    return list
      .filter(allowed)
      .map((d) => ({ id: `page-${d.key}`, kind: "page", title: t(`pages.${d.key}`), href: d.href }))
      .filter((o) => matches(o.title, query))
      .slice(0, PAGE_LIMIT);
  }, [allowed, query, ready, scope, t]);

  const settings = useMemo((): Option[] => {
    if (!ready || scope !== "staff") return [];
    const all = (messages as { settings?: Record<string, Record<string, { label?: string }>> })
      .settings;
    const found: Option[] = [];
    for (const [prefix, entries] of Object.entries(all ?? {})) {
      const where = SETTING_PAGES[prefix];
      if (!where || (where.feature && !feature(where.feature))) continue;
      for (const [name, entry] of Object.entries(entries)) {
        if (entry?.label && matches(entry.label, query)) {
          found.push({
            id: `setting-${prefix}.${name}`,
            kind: "setting",
            title: entry.label,
            href: where.href,
          });
        }
      }
    }
    return found.slice(0, PAGE_LIMIT);
  }, [feature, messages, query, ready, scope]);

  const options = useMemo((): Option[] => {
    if (!text.trim()) {
      return recent.map((r, i) => ({
        id: `recent-${i}`,
        kind: "recent",
        title: r,
        run: () => setText(r),
      }));
    }
    const out: Option[] = [];
    const jump = results?.jump;
    if (jump) {
      out.push({
        id: `jump-${jump.id}`,
        kind: jump.type,
        title: jump.title || t("draft"),
        detail: jump.detail,
        href: RECORD_PAGES[jump.type]?.(jump.id),
        hit: jump,
      });
    }
    for (const group of results?.groups ?? []) {
      for (const hit of group.hits) {
        if (jump && hit.id === jump.id) continue;
        out.push({
          id: `${group.type}-${hit.id}`,
          kind: group.type,
          title: hit.title || t("draft"),
          detail: hit.detail,
          href: RECORD_PAGES[group.type]?.(hit.id),
          hit,
        });
      }
      const list = LISTS[group.type];
      if (group.more && list) {
        out.push({
          id: `more-${group.type}`,
          kind: "more",
          title: t("seeAll", { kind: t(`types.${group.type}`) }),
          href: `${list}?q=${encodeURIComponent(results?.query ?? query)}`,
        });
      }
    }
    out.push(...pages, ...settings);
    if (scope === "platform" && ready) {
      out.push({
        id: "people",
        kind: "people",
        title: t("people.find", { text: query }),
        detail: t("people.audited"),
        run: () => setPeople(query),
      });
      for (const person of peopleQuery.data?.data ?? []) {
        out.push({
          id: `person-${person.kind}-${person.id}`,
          kind: "people",
          title:
            person.kind === "SHOP"
              ? `${person.shop_name} (${person.name})`
              : person.name || person.email,
          detail: [person.tenant_name, person.email || person.phone].filter(Boolean).join(" · "),
          href: `/platform/tenants/${person.tenant_id}`,
          person,
        });
      }
    }
    // ADR-053: 9e adds "Ask the assistant" here, after the records, pages and settings.
    return out;
  }, [pages, peopleQuery.data, query, ready, recent, results, scope, settings, t, text]);

  const current = Math.min(active, Math.max(options.length - 1, 0));
  const sections = useMemo(
    () =>
      options.map((option, index) => {
        const section = sectionOf(option);
        if (section === "more") return null;
        // A heading where the section starts (a "See all" row stays in its group).
        const previous = options
          .slice(0, index)
          .map(sectionOf)
          .filter((s) => s !== "more")
          .at(-1);
        return section !== previous ? headingFor(option, t) : null;
      }),
    [options, t],
  );

  function choose(option: Option | undefined) {
    if (!option) return;
    if (option.run) {
      option.run();
      inputRef.current?.focus();
      return;
    }
    if (!option.href) return;
    setRecent(rememberSearch(me?.id, text));
    onClose();
    router.push(option.href);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive(options.length ? (current + 1) % options.length : 0);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive(options.length ? (current - 1 + options.length) % options.length : 0);
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(options[current]);
    }
  }

  const waiting = ready && (records.isPending || query !== text.trim());
  const failed = ready && records.isError;
  const activeId = options[current] ? `${listId}-${options[current].id}` : undefined;

  return (
    <DialogContent
      showCloseButton={false}
      className="flex max-h-dvh flex-col gap-0 overflow-hidden p-0 max-md:h-dvh max-md:max-w-none max-md:rounded-none md:top-[12%] md:max-w-2xl md:translate-y-0"
      onOpenAutoFocus={(event) => {
        event.preventDefault();
        inputRef.current?.focus();
      }}
    >
      <DialogTitle className="sr-only">{t("title")}</DialogTitle>
      <DialogDescription className="sr-only">{t("description")}</DialogDescription>
      <div className="flex items-center gap-2 border-b px-3">
        <Search aria-hidden className="text-muted-foreground size-4 shrink-0" />
        <input
          ref={inputRef}
          role="combobox"
          aria-expanded={options.length > 0}
          aria-controls={listId}
          aria-activedescendant={activeId}
          aria-autocomplete="list"
          aria-label={t("label")}
          placeholder={scope === "staff" ? t("hint") : t("platformHint")}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
          className="min-h-12 min-w-0 flex-1 bg-transparent text-base outline-none md:text-sm"
        />
        <Button variant="ghost" size="sm" onClick={onClose} className="shrink-0">
          {t("close")}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2 md:max-h-[60vh]">
        {!text.trim() && recent.length === 0 ? (
          <p className="text-muted-foreground px-2 py-6 text-center text-sm">{t("start")}</p>
        ) : null}
        {text.trim() && !ready ? (
          <p className="text-muted-foreground px-2 py-6 text-center text-sm">{t("typeMore")}</p>
        ) : null}
        {failed ? (
          <div className="flex flex-col items-center gap-2 px-2 py-6 text-center text-sm">
            <p>{t("failed")}</p>
            <Button variant="outline" size="sm" onClick={() => records.refetch()}>
              {t("retry")}
            </Button>
          </div>
        ) : null}
        <ul id={listId} role="listbox" aria-label={t("results")} className="space-y-0.5">
          {options.map((option, index) => {
            const heading = sections[index];
            const Icon = ICONS[option.kind] ?? Search;
            const selected = index === current;
            return (
              <li key={option.id} role="presentation">
                {heading ? (
                  <p
                    role="presentation"
                    className="text-muted-foreground px-2 pt-3 pb-1 text-xs font-semibold tracking-wide uppercase"
                  >
                    {heading}
                  </p>
                ) : null}
                <div
                  id={`${listId}-${option.id}`}
                  role="option"
                  aria-selected={selected}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(option)}
                  className={cn(
                    "flex min-h-11 cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5",
                    selected ? "bg-brand-100 text-brand-900" : "hover:bg-muted",
                    option.kind === "more" && "text-primary text-sm",
                  )}
                >
                  {option.kind === "more" ? (
                    <span className="size-4" aria-hidden />
                  ) : (
                    <Icon aria-hidden className="text-muted-foreground size-4 shrink-0" />
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{option.title}</span>
                    {option.detail ? (
                      <span className="text-muted-foreground block truncate text-xs">
                        {option.detail}
                      </span>
                    ) : null}
                  </span>
                  {option.hit ? <HitFacts hit={option.hit} /> : null}
                </div>
              </li>
            );
          })}
        </ul>
        {waiting && !results ? (
          <div className="space-y-2 p-2" aria-label={t("searching")} role="status">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-2/3" />
          </div>
        ) : null}
        {ready && !waiting && !failed && options.length === (scope === "platform" ? 1 : 0) ? (
          <p className="text-muted-foreground px-2 py-6 text-center text-sm">
            {t("nothing", { text: query })}
          </p>
        ) : null}
      </div>
      <p className="text-muted-foreground hidden border-t px-3 py-2 text-xs md:block">
        {t("keys")}
      </p>
    </DialogContent>
  );
}

function sectionOf(option: Option): string {
  return option.id.startsWith("jump-") ? "jump" : option.kind;
}

function headingFor(option: Option, t: ReturnType<typeof useTranslations>): string {
  if (option.kind === "recent") return t("recent");
  if (option.kind === "page") return t("types.page");
  if (option.kind === "setting") return t("types.setting");
  if (option.kind === "people") return t("types.people");
  if (option.id.startsWith("jump-")) return t("bestMatch");
  return t(`types.${option.kind}`);
}

function HitFacts({ hit }: { hit: SearchHit }) {
  const t = useTranslations("search");
  return (
    <span className="text-muted-foreground flex shrink-0 flex-col items-end text-xs max-sm:hidden">
      {hit.amount ? <MoneyText value={hit.amount} /> : null}
      {hit.date ? <DateText value={hit.date} /> : null}
      {NOTED.has(hit.status) ? <span>{t(`status.${hit.status}`)}</span> : null}
    </span>
  );
}
