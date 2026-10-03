"use client";

import { X } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCatalogProductsSearch } from "@/lib/api/generated/endpoints/catalog/catalog";
import { useRetailersList } from "@/lib/api/generated/endpoints/retailers/retailers";
import { useTranslations } from "@/lib/i18n/translations";
import { useDebounced } from "@/lib/use-debounced";

export interface Picked {
  id: string;
  label: string;
}

interface PickerProps {
  id?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
  value: Picked | null;
  onChange: (value: Picked | null) => void;
  placeholder?: string;
}

/**
 * Type to search, then choose from the server's matches (a small ARIA combobox). Used inside a
 * `FormField`, which supplies the id that the label points at.
 */
function SearchPicker({
  id,
  "aria-describedby": describedBy,
  "aria-invalid": invalid,
  value,
  onChange,
  placeholder,
  useResults,
}: PickerProps & { useResults: (text: string) => { items: Picked[]; loading: boolean } }) {
  const t = useTranslations("pricing.picker");
  const listId = useId();
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const query = useDebounced(text.trim());
  const { items, loading } = useResults(query);

  if (value) {
    return (
      <div className="flex min-h-10 items-center justify-between gap-2 rounded-md border px-3">
        <span id={id} className="truncate text-sm">
          {value.label}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label={t("change", { name: value.label })}
          onClick={() => onChange(null)}
        >
          <X aria-hidden />
        </Button>
      </div>
    );
  }
  const choose = (item: Picked) => {
    onChange(item);
    setText("");
    setOpen(false);
  };
  return (
    <div className="relative">
      <Input
        id={id}
        role="combobox"
        aria-expanded={open && query.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-describedby={describedBy}
        aria-invalid={invalid}
        autoComplete="off"
        className="h-10"
        value={text}
        placeholder={placeholder ?? t("typeToSearch")}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive((i) => Math.min(i + 1, items.length - 1));
          else if (e.key === "ArrowUp") setActive((i) => Math.max(i - 1, 0));
          else if (e.key === "Enter" && items[active]) {
            e.preventDefault();
            choose(items[active]);
          } else if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && query ? (
        <ul
          id={listId}
          role="listbox"
          className="bg-popover absolute z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-md border p-1 shadow-md"
        >
          {items.length === 0 ? (
            <li className="text-muted-foreground px-2 py-2 text-sm">
              {loading ? t("searching") : t("noMatches")}
            </li>
          ) : (
            items.map((item, index) => (
              <li
                key={item.id}
                role="option"
                aria-selected={index === active}
                className="aria-selected:bg-muted min-h-10 cursor-pointer rounded px-2 py-2 text-sm"
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(item);
                }}
              >
                {item.label}
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}

function useProductResults(text: string) {
  const query = useCatalogProductsSearch({ q: text }, { query: { enabled: text.length > 0 } });
  return {
    items: (query.data?.data ?? []).map((p) => ({ id: p.id, label: `${p.name} (${p.code})` })),
    loading: query.isFetching,
  };
}

function useRetailerResults(text: string) {
  const query = useRetailersList(
    { search: text, page_size: 20 },
    { query: { enabled: text.length > 0 } },
  );
  return {
    items: (query.data?.data.results ?? []).map((r) => ({
      id: r.id,
      label: `${r.shop_name} (${r.code})`,
    })),
    loading: query.isFetching,
  };
}

export function ProductPicker(props: PickerProps) {
  return <SearchPicker {...props} useResults={useProductResults} />;
}

export function RetailerPicker(props: PickerProps) {
  return <SearchPicker {...props} useResults={useRetailerResults} />;
}
