"use client";

import { RotateCcw, Save } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { Setting } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { omitKey } from "@/lib/utils";

export const GROUP_ORDER = [
  "tax",
  "invoicing",
  "orders",
  "pricing",
  "retailers",
  "stock",
  "credit_payments",
  "notifications",
  "security",
];

type Draft = Record<string, unknown>;

interface RegistrySettingsFormProps {
  rows: Setting[];
  /** Only these groups (e.g. one policy page); default: all groups present. */
  groups?: string[];
  /** Send changed values; resolve with the fresh rows from the server. */
  onSave: (values: Draft) => Promise<Setting[]>;
  onReset: (key: string) => Promise<Setting[]>;
}

/**
 * The settings UI generated from the registry (ADR-016, PLAN §9): a control per type, the
 * plain-language description beside each, default badge and reset, dependencies explained, and a
 * note for settings copied onto documents. The server validates; this only sends user intent.
 */
export function RegistrySettingsForm({
  rows: initialRows,
  groups,
  onSave,
  onReset,
}: RegistrySettingsFormProps) {
  const t = useTranslations();
  const tf = useTranslations("settingsForm");
  const errors = useErrorText();
  const [rows, setRows] = useState(initialRows);
  const [draft, setDraft] = useState<Draft>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const byKey = new Map(rows.map((row) => [row.key, row]));
  const valueOf = (key: string) => (key in draft ? draft[key] : byKey.get(key)?.value);
  const label = (key: string) =>
    t.has(`settings.${key}.label`) ? t(`settings.${key}.label`) : key;
  const optionLabel = (key: string, value: unknown) =>
    t.has(`settings.${key}.options.${String(value)}`)
      ? t(`settings.${key}.options.${String(value)}`)
      : String(value);
  const describe = (row: Setting) =>
    t.has(`settings.${row.key}.description`)
      ? t(`settings.${row.key}.description`)
      : row.description;

  function dependencyNote(row: Setting): string | null {
    const dep = row.depends_on;
    if (!dep) return null;
    const current = valueOf(dep.key);
    if (dep.not_null)
      return current === null || current === ""
        ? tf("dependsOnSet", { setting: label(dep.key) })
        : null;
    if (current === dep.equals) return null;
    const expected =
      typeof dep.equals === "boolean"
        ? tf(dep.equals ? "on" : "off")
        : optionLabel(dep.key, dep.equals);
    return tf("dependsOn", { setting: label(dep.key), value: expected });
  }

  const change = (key: string, value: unknown) => {
    setDraft((current) => {
      const next = { ...current, [key]: value };
      if (byKey.get(key)?.value === value) delete next[key];
      return next;
    });
    setFieldErrors((current) => omitKey(current, key));
  };

  async function save() {
    setBusy(true);
    setFieldErrors({});
    try {
      setRows(await onSave(draft));
      setDraft({});
      toast.success(tf("saved"));
    } catch (err) {
      const fields = errors.fields(err);
      setFieldErrors(fields);
      if (Object.keys(fields).length === 0) toast.error(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  async function reset(key: string) {
    setBusy(true);
    try {
      setRows(await onReset(key));
      setDraft((current) => omitKey(current, key));
    } catch (err) {
      toast.error(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  function control(row: Setting, disabled: boolean) {
    const id = `setting-${row.key}`;
    const value = valueOf(row.key);
    const common = { id, disabled, "aria-describedby": `${id}-description` };
    if (row.type === "bool") {
      return (
        <Switch
          {...common}
          checked={Boolean(value)}
          onCheckedChange={(checked) => change(row.key, checked)}
        />
      );
    }
    if (row.allowed.length > 0) {
      return (
        <Select
          disabled={disabled}
          value={value === null || value === undefined ? "" : String(value)}
          onValueChange={(next) => change(row.key, row.type === "int" ? Number(next) : next)}
        >
          <SelectTrigger
            id={id}
            className="min-h-10 w-full sm:w-80"
            aria-describedby={`${id}-description`}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {row.allowed.map((option) => {
              const reserved = row.reserved_values.includes(option);
              return (
                <SelectItem key={String(option)} value={String(option)} disabled={reserved}>
                  {optionLabel(row.key, option)}
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>
      );
    }
    if (row.type === "int" || row.type === "money") {
      return (
        <div className="flex items-center gap-2">
          {row.type === "money" ? (
            <span aria-hidden className="text-muted-foreground">
              ₹
            </span>
          ) : null}
          <Input
            {...common}
            inputMode={row.type === "money" ? "decimal" : "numeric"}
            className="h-10 w-40 tabular-nums"
            placeholder={row.nullable ? tf("noneOption") : undefined}
            value={value === null || value === undefined ? "" : String(value)}
            onChange={(e) => {
              const raw = e.target.value.trim();
              if (raw === "" && row.nullable) change(row.key, null);
              else if (row.type === "int") change(row.key, /^-?\d+$/.test(raw) ? Number(raw) : raw);
              else change(row.key, raw); // money stays a decimal string, never a float
            }}
          />
        </div>
      );
    }
    return (
      <Input
        {...common}
        className="h-10 w-full sm:w-80"
        value={value === null || value === undefined ? "" : String(value)}
        onChange={(e) => change(row.key, e.target.value)}
      />
    );
  }

  const visibleGroups = (groups ?? GROUP_ORDER).filter((g) => rows.some((row) => row.group === g));
  const dirty = Object.keys(draft).length;

  return (
    <div className="space-y-6 pb-20">
      {visibleGroups.map((group) => (
        <Card key={group}>
          <CardHeader>
            <CardTitle>
              <h2 className="text-lg">{tf(`groups.${group}`)}</h2>
            </CardTitle>
          </CardHeader>
          <CardContent className="divide-y">
            {rows
              .filter((row) => row.group === group && row.status === "ACTIVE")
              .map((row) => {
                const note = dependencyNote(row);
                const disabled = !row.can_edit || busy || note !== null;
                const id = `setting-${row.key}`;
                return (
                  <div
                    key={row.key}
                    className="grid gap-3 py-4 first:pt-0 last:pb-0 md:grid-cols-[1fr_auto] md:items-start"
                  >
                    <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Label htmlFor={id} className="text-sm font-medium">
                          {label(row.key)}
                        </Label>
                        {row.is_default && !(row.key in draft) ? (
                          <Badge variant="secondary">{tf("default")}</Badge>
                        ) : null}
                      </div>
                      <p id={`${id}-description`} className="text-muted-foreground text-sm">
                        {describe(row)}
                      </p>
                      {note ? <p className="text-muted-foreground text-xs italic">{note}</p> : null}
                      {row.snapshot_on.length > 0 ? (
                        <p className="text-muted-foreground text-xs">{tf("snapshotNote")}</p>
                      ) : null}
                      {!row.can_edit ? (
                        <p className="text-muted-foreground text-xs">{tf("readOnly")}</p>
                      ) : null}
                      {fieldErrors[row.key] ? (
                        <p role="alert" className="text-destructive text-xs font-medium">
                          {fieldErrors[row.key]}
                        </p>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-2">
                      {control(row, disabled)}
                      {!row.is_default && row.can_edit ? (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-10"
                          aria-label={`${tf("reset")}: ${label(row.key)}`}
                          disabled={busy}
                          onClick={() => void reset(row.key)}
                        >
                          <RotateCcw aria-hidden />
                        </Button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
          </CardContent>
        </Card>
      ))}
      {dirty > 0 ? (
        <div className="bg-background/95 fixed inset-x-0 bottom-0 z-30 border-t px-4 py-3 backdrop-blur md:left-60">
          <div className="mx-auto flex max-w-5xl items-center justify-end gap-3">
            <span className="text-muted-foreground mr-auto text-sm" aria-live="polite">
              {tf("unsaved", { count: dirty })}
            </span>
            <Button variant="outline" onClick={() => setDraft({})} disabled={busy}>
              {tf("discard")}
            </Button>
            <Button onClick={() => void save()} disabled={busy} className="min-h-10">
              <Save aria-hidden />
              {tf("save")}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
