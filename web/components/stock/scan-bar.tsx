"use client";

import { Loader2, ScanBarcode } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState, type KeyboardEvent } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { QtyText } from "@/components/shared/money-text";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { catalogProductBarcodesCreate } from "@/lib/api/generated/endpoints/catalog/catalog";
import { stockLookup, useStockList } from "@/lib/api/generated/endpoints/inventory/inventory";
import type { StockRow } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { useDebounced } from "@/lib/use-debounced";

import { CameraButton } from "./camera-scanner";

/** A code typed or scanned in one go: no spaces (names have spaces, codes and barcodes don't). */
const looksLikeCode = (text: string) => /^\S{3,64}$/.test(text);

/**
 * Scan or search, for goods receipts and adjustments (ADR-041 item 14).
 * - A USB/Bluetooth scanner types the code and presses Enter: the exact product is looked up.
 * - Typing a name shows matches to tap (44 px rows on phones).
 * - The camera button scans with the phone camera where the browser allows it.
 * - An unknown code can be linked to a product on the spot by staff who manage products.
 */
export function ScanBar({
  onPick,
  autoFocus = false,
  inputRef,
}: {
  onPick: (product: StockRow) => void;
  autoFocus?: boolean;
  inputRef?: React.RefObject<HTMLInputElement | null>;
}) {
  const t = useTranslations("stock.scan");
  const { can } = useAuth();
  const errors = useErrorText();
  const listId = useId();
  const ownRef = useRef<HTMLInputElement>(null);
  const field = inputRef ?? ownRef;
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState<string | null>(null);
  const [linking, setLinking] = useState<string | null>(null);
  const search = useDebounced(text.trim());
  const matches = useStockList(
    { search, page_size: 8 },
    { query: { enabled: search.length >= 2 } },
  );
  const results = search.length >= 2 ? (matches.data?.data.results ?? []) : [];

  function done(product: StockRow) {
    setText("");
    setUnknown(null);
    onPick(product);
    field.current?.focus();
  }

  async function pick(product: StockRow) {
    if (linking) {
      try {
        await catalogProductBarcodesCreate(product.id, { barcode: linking });
        toast.success(t("linked", { code: linking, name: product.name }));
      } catch (err) {
        toast.error(errors.message(err));
        return;
      }
      setLinking(null);
    }
    done(product);
  }

  async function lookUp(code: string) {
    setBusy(true);
    try {
      const response = await stockLookup({ code });
      if (response.status === 200) done(response.data);
      else setUnknown(code);
    } catch {
      setUnknown(code);
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    if (results.length === 1 && !looksLikeCode(value)) void pick(results[0]!);
    else if (looksLikeCode(value)) void lookUp(value);
    else if (results.length) void pick(results[0]!);
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <ScanBarcode
            aria-hidden
            className="text-muted-foreground absolute top-1/2 left-3 size-5 -translate-y-1/2"
          />
          <Input
            ref={field}
            autoFocus={autoFocus}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setUnknown(null);
            }}
            onKeyDown={onKeyDown}
            placeholder={linking ? t("linkPlaceholder") : t("placeholder")}
            aria-label={t("label")}
            aria-controls={listId}
            autoComplete="off"
            enterKeyHint="search"
            className="h-12 pl-10 text-base"
          />
          {busy ? (
            <Loader2
              aria-hidden
              className="text-muted-foreground absolute top-1/2 right-3 size-4 -translate-y-1/2 animate-spin"
            />
          ) : null}
        </div>
        <CameraButton
          onCode={(code) => {
            setText(code);
            void lookUp(code);
          }}
        />
      </div>
      {linking ? (
        <p className="bg-info/10 rounded-lg px-3 py-2 text-sm">
          {t("linkingHelp", { code: linking })}{" "}
          <button
            type="button"
            className="text-primary font-medium"
            onClick={() => setLinking(null)}
          >
            {t("cancel")}
          </button>
        </p>
      ) : null}
      {unknown ? (
        <div role="alert" className="bg-warning/10 space-y-2 rounded-lg px-3 py-2 text-sm">
          <p>{t("notFound", { code: unknown })}</p>
          {can("products.manage") ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setLinking(unknown);
                setUnknown(null);
                setText("");
                field.current?.focus();
              }}
            >
              {t("link")}
            </Button>
          ) : null}
        </div>
      ) : null}
      {results.length ? (
        <ul id={listId} aria-label={t("matches")} className="divide-y rounded-lg border">
          {results.map((product) => (
            <li key={product.id}>
              <button
                type="button"
                onClick={() => void pick(product)}
                className="hover:bg-muted flex min-h-11 w-full items-center justify-between gap-3 px-3 py-2 text-left"
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">{product.name}</span>
                  <span className="text-muted-foreground block text-xs">{product.code}</span>
                </span>
                <span className="text-muted-foreground shrink-0 text-xs">
                  {t("inStock")} <QtyText value={product.on_hand} unit={product.unit.code} />
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
