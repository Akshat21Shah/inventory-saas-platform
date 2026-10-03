"use client";

import { useTranslations } from "@/lib/i18n/translations";
import { useState, type FormEvent, type ReactNode } from "react";

import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { Button } from "@/components/ui/button";
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
import { Switch } from "@/components/ui/switch";
import { useErrorText } from "@/lib/api/use-error-text";

export type FieldValue = string | boolean;

export interface FieldSpec {
  name: string;
  label: string;
  kind?: "text" | "decimal" | "int" | "date" | "bool" | "select";
  hint?: string;
  required?: boolean;
  options?: { value: string; label: string }[];
  /** Shown but not editable (e.g. a code that is fixed after creation). */
  readOnly?: boolean;
}

/**
 * A small create/edit form in a dialog for the platform master tables. Values stay strings
 * (decimals are never parsed into floats); the server validates and its field errors show inline.
 */
export function FieldsDialog({
  trigger,
  title,
  description,
  fields,
  initial,
  submitLabel,
  onSubmit,
}: {
  trigger: ReactNode;
  title: string;
  description?: string;
  fields: FieldSpec[];
  initial: Record<string, FieldValue>;
  submitLabel: string;
  onSubmit: (values: Record<string, FieldValue>) => Promise<void>;
}) {
  const tc = useTranslations("common");
  const errors = useErrorText();
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState(initial);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFieldErrors({});
    setFormError(null);
    try {
      await onSubmit(values);
      setOpen(false);
    } catch (err) {
      const fieldMessages = errors.fields(err);
      setFieldErrors(fieldMessages);
      if (Object.keys(fieldMessages).length === 0) setFormError(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setValues(initial);
          setFieldErrors({});
          setFormError(null);
        }
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <form onSubmit={submit} className="space-y-4" noValidate>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description ? <DialogDescription>{description}</DialogDescription> : null}
          </DialogHeader>
          {fields.map((field) => {
            const value = values[field.name];
            if (field.kind === "bool") {
              return (
                <label key={field.name} className="flex items-center justify-between gap-4">
                  <span className="text-sm font-medium">{field.label}</span>
                  <Switch
                    checked={Boolean(value)}
                    disabled={field.readOnly}
                    onCheckedChange={(checked) =>
                      setValues((v) => ({ ...v, [field.name]: checked }))
                    }
                  />
                </label>
              );
            }
            if (field.kind === "select") {
              return (
                <FormField
                  key={field.name}
                  label={field.label}
                  hint={field.hint}
                  error={fieldErrors[field.name]}
                  required={field.required}
                >
                  <FormSelect
                    value={String(value ?? "")}
                    disabled={field.readOnly}
                    onValueChange={(next) => setValues((v) => ({ ...v, [field.name]: next }))}
                    options={field.options ?? []}
                  />
                </FormField>
              );
            }
            return (
              <FormField
                key={field.name}
                label={field.label}
                hint={field.hint}
                error={fieldErrors[field.name]}
                required={field.required}
              >
                <Input
                  className="h-10"
                  type={field.kind === "date" ? "date" : "text"}
                  inputMode={
                    field.kind === "decimal"
                      ? "decimal"
                      : field.kind === "int"
                        ? "numeric"
                        : undefined
                  }
                  readOnly={field.readOnly}
                  value={String(value ?? "")}
                  onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
                />
              </FormField>
            );
          })}
          {formError ? (
            <p role="alert" className="text-destructive text-sm font-medium">
              {formError}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              {tc("cancel")}
            </Button>
            <Button type="submit" disabled={busy} className="min-h-10">
              {submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Blank optional integers become null ("no limit"). Anything that is not a whole number is sent
 * as typed so the server answers with its own field error. */
export function intOrNull(value: FieldValue | undefined): number | null {
  const text = String(value ?? "").trim();
  if (text === "") return null;
  return /^\d+$/.test(text) ? Number(text) : (text as unknown as number);
}
