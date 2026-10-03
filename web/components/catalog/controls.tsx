"use client";

import { useTranslations } from "@/lib/i18n/translations";
import { useState } from "react";

import { FormField } from "@/components/shared/form-field";
import { FormSelect } from "@/components/shared/form-select";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

import type { Option } from "./options";

/** A labelled filter for table toolbars (the label is for screen readers). */
export function FilterSelect({
  label,
  value,
  onChange,
  options,
  className,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Option[];
  className?: string;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={label} className={cn("min-h-10 w-full sm:w-44", className)}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** "Choose one and apply" for bulk actions such as "set category". */
export function PickDialog({
  trigger,
  title,
  label,
  options,
  onPick,
}: {
  trigger: string;
  title: string;
  label: string;
  options: Option[];
  onPick: (value: string) => Promise<void>;
}) {
  const t = useTranslations("common");
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setValue("");
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          {trigger}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <FormField label={label} required>
          <FormSelect value={value} onValueChange={setValue} options={options} />
        </FormField>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            {t("cancel")}
          </Button>
          <Button
            disabled={!value || busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onPick(value);
                setOpen(false);
              } finally {
                setBusy(false);
              }
            }}
          >
            {t("confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
