"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface SelectOption {
  value: string;
  label: string;
}

/**
 * A Select for use inside `FormField`: the field's id and ARIA attributes land on the trigger, so
 * the label names the control for screen readers (the Select root would drop them).
 */
export function FormSelect({
  id,
  "aria-describedby": describedBy,
  "aria-invalid": invalid,
  "aria-label": label,
  value,
  onValueChange,
  options,
  disabled,
  placeholder,
}: {
  id?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
  /** When there is no visible label (e.g. a choice in a list row). */
  "aria-label"?: string;
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  disabled?: boolean;
  placeholder?: string;
}) {
  return (
    <Select value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectTrigger
        id={id}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        aria-label={label}
        className="min-h-10 w-full"
      >
        <SelectValue placeholder={placeholder} />
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
