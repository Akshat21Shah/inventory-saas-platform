"use client";

import { useTranslations } from "next-intl";
import { useCallback, useId, useMemo, useState, type ReactNode } from "react";

import { FilterSelect } from "@/components/catalog/controls";
import { useBrandOptions, useCategoryOptions } from "@/components/catalog/options";
import { ProductPicker, RetailerPicker } from "@/components/pricing/pickers";
import { useSalespeopleOptions } from "@/components/retailers/options";
import { FilterBar } from "@/components/shared/filter-bar";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import type { Filter, Report } from "@/lib/api/generated/model";

import type { ReportWords } from "./words";

export type FilterValues = Record<string, string>;
const ANY = "__any";
const STORE = "report-filters:";

interface Remembered {
  values: FilterValues;
  /** The chosen shop's or product's name, so its picker shows it. */
  labels: FilterValues;
}

/** What this person last chose on this report, in this browser only (ADR-050). Dates aren't
 * kept: a report opens on its default period (this month) every time. */
function recall(report: Report): Remembered {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORE + report.code) ?? "{}") as
      Partial<Remembered> | undefined;
    const values: FilterValues = {};
    for (const f of report.filters) {
      const value = saved?.values?.[f.key];
      if (f.kind === "date" || typeof value !== "string") continue;
      if (f.kind === "choice" && value && !f.choices.includes(value)) continue;
      values[f.key] = value;
    }
    return { values, labels: saved?.labels ?? {} };
  } catch {
    return { values: {}, labels: {} };
  }
}

function keep(report: Report, state: Remembered): void {
  const dates = new Set(report.filters.filter((f) => f.kind === "date").map((f) => f.key));
  const values = Object.fromEntries(
    Object.entries(state.values).filter(([key]) => !dates.has(key)),
  );
  try {
    window.localStorage.setItem(STORE + report.code, JSON.stringify({ ...state, values }));
  } catch {
    // storage unavailable (private window, blocked): the filters just aren't remembered
  }
}

/** The report's filters: its defaults, then what was last chosen here. The report screen mounts
 * only in the browser (after the catalogue loads), so storage can be read on the first render. */
export function useReportFilters(report: Report) {
  const defaults = useMemo(
    () => Object.fromEntries(report.filters.map((f) => [f.key, f.default ?? ""])),
    [report],
  );
  const [state, setState] = useState<Remembered>(() => {
    const remembered = recall(report);
    return { values: { ...defaults, ...remembered.values }, labels: remembered.labels };
  });
  const set = useCallback(
    (key: string, value: string, label?: string) => {
      setState((previous) => {
        const next = {
          values: { ...previous.values, [key]: value },
          labels: label === undefined ? previous.labels : { ...previous.labels, [key]: label },
        };
        keep(report, next);
        return next;
      });
    },
    [report],
  );
  const reset = useCallback(() => {
    const next = { values: defaults, labels: {} };
    setState(next);
    keep(report, next);
  }, [report, defaults]);
  const active = report.filters.filter(
    (f) => (state.values[f.key] ?? "") !== (defaults[f.key] ?? ""),
  ).length;
  /** Only the filters with a value, as the server reads them. */
  const chosen = useMemo(
    () => Object.fromEntries(Object.entries(state.values).filter(([, value]) => value !== "")),
    [state.values],
  );
  return { values: state.values, labels: state.labels, chosen, set, reset, active };
}

export type ReportFilters = ReturnType<typeof useReportFilters>;

interface ControlProps {
  filter: Filter;
  filters: ReportFilters;
  words: ReportWords;
  onChange: () => void;
}

function Labelled({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 text-xs sm:w-52">
      <label htmlFor={id}>{label}</label>
      {children}
    </div>
  );
}

function OptionsControl({
  filter,
  filters,
  words,
  onChange,
  options,
  anyLabel,
}: ControlProps & { options: { value: string; label: string }[]; anyLabel: string }) {
  const value = filters.values[filter.key] || ANY;
  return (
    <FilterSelect
      label={words.filter(filter.key, filter.label)}
      value={value}
      onChange={(next) => {
        filters.set(filter.key, next === ANY ? "" : next);
        onChange();
      }}
      options={[...(filter.required ? [] : [{ value: ANY, label: anyLabel }]), ...options]}
    />
  );
}

function CategoryControl(props: ControlProps) {
  const t = useTranslations("reports.viewer");
  return <OptionsControl {...props} options={useCategoryOptions()} anyLabel={t("any")} />;
}

function BrandControl(props: ControlProps) {
  const t = useTranslations("reports.viewer");
  return <OptionsControl {...props} options={useBrandOptions()} anyLabel={t("any")} />;
}

function StaffControl(props: ControlProps) {
  const t = useTranslations("reports.viewer");
  return <OptionsControl {...props} options={useSalespeopleOptions()} anyLabel={t("any")} />;
}

function PickerControl({ filter, filters, words, onChange }: ControlProps) {
  const t = useTranslations("reports.viewer");
  const id = useId();
  const Picker = filter.entity === "product" ? ProductPicker : RetailerPicker;
  const current = filters.values[filter.key];
  return (
    <Labelled id={id} label={words.filter(filter.key, filter.label)}>
      <Picker
        id={id}
        value={current ? { id: current, label: filters.labels[filter.key] ?? current } : null}
        onChange={(picked) => {
          filters.set(filter.key, picked?.id ?? "", picked?.label ?? "");
          onChange();
        }}
        placeholder={filter.entity === "product" ? t("searchProduct") : t("searchShop")}
      />
    </Labelled>
  );
}

function FilterControl(props: ControlProps) {
  const { filter, filters, words, onChange } = props;
  const t = useTranslations("reports.viewer");
  const id = useId();
  const label = words.filter(filter.key, filter.label);
  switch (filter.kind) {
    case "date":
      return (
        <Labelled id={id} label={label}>
          <Input
            id={id}
            type="date"
            className="min-h-10"
            value={filters.values[filter.key] ?? ""}
            required={filter.required}
            onChange={(e) => {
              filters.set(filter.key, e.target.value);
              onChange();
            }}
          />
        </Labelled>
      );
    case "choice":
      return (
        <OptionsControl
          {...props}
          options={filter.choices.map((value) => ({
            value,
            label: words.choice(filter.key, value),
          }))}
          anyLabel={t("any")}
        />
      );
    case "bool":
      return (
        <label className="flex min-h-10 items-center gap-2 text-sm">
          <Checkbox
            checked={filters.values[filter.key] === "true"}
            onCheckedChange={(checked) => {
              filters.set(filter.key, checked === true ? "true" : "");
              onChange();
            }}
          />
          {label}
        </label>
      );
    case "id":
      if (filter.entity === "category") return <CategoryControl {...props} />;
      if (filter.entity === "brand") return <BrandControl {...props} />;
      if (filter.entity === "staff") return <StaffControl {...props} />;
      return <PickerControl {...props} />;
    default:
      return (
        <Labelled id={id} label={label}>
          <Input
            id={id}
            className="min-h-10"
            value={filters.values[filter.key] ?? ""}
            onChange={(e) => {
              filters.set(filter.key, e.target.value);
              onChange();
            }}
          />
        </Labelled>
      );
  }
}

/** The period stays in view on phones; the other filters open from "Filters (n)". */
export function ReportFilterBar({
  report,
  filters,
  words,
  onChange,
}: {
  report: Report;
  filters: ReportFilters;
  words: ReportWords;
  onChange: () => void;
}) {
  const period = report.filters.filter((f) => f.kind === "date");
  const others = report.filters.filter((f) => f.kind !== "date");
  const control = (f: Filter) => (
    <FilterControl key={f.key} filter={f} filters={filters} words={words} onChange={onChange} />
  );
  // Phones: the period on its own full-width row (two dates side by side), then "Filters (n)"
  // for the rest. Wider screens: all in one row.
  return (
    <div className="flex flex-wrap items-end gap-3">
      {period.length ? (
        <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto sm:gap-3">
          {period.map(control)}
        </div>
      ) : null}
      {others.length ? (
        <FilterBar
          filters={<>{others.map(control)}</>}
          active={filters.active}
          onClear={() => {
            filters.reset();
            onChange();
          }}
        />
      ) : null}
    </div>
  );
}
