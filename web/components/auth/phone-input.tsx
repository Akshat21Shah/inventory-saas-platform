"use client";

import type { ComponentProps } from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/** 10-digit Indian mobile number with a fixed +91 prefix. The label targets the input itself
 * (FormField passes id / aria-* here), so screen readers announce it correctly. */
export function PhoneInput({
  className,
  onChange,
  ...props
}: Omit<ComponentProps<typeof Input>, "type">) {
  return (
    <div className="flex items-stretch">
      <span
        aria-hidden
        className="bg-muted text-muted-foreground flex items-center rounded-l-md border border-r-0 px-3 text-lg"
      >
        +91
      </span>
      <Input
        type="tel"
        inputMode="numeric"
        autoComplete="tel-national"
        maxLength={10}
        className={cn("h-14 rounded-l-none text-xl tracking-wider", className)}
        onChange={(event) => {
          event.target.value = event.target.value.replace(/\D/g, "").slice(0, 10);
          onChange?.(event);
        }}
        {...props}
      />
    </div>
  );
}
