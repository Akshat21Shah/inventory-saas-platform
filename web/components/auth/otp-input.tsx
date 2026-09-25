"use client";

import { forwardRef, type ComponentProps } from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/** One large field for a 6-digit code: numeric keypad, SMS/app autofill, digits only. */
export const OtpInput = forwardRef<HTMLInputElement, Omit<ComponentProps<typeof Input>, "type">>(
  function OtpInput({ className, onChange, ...props }, ref) {
    return (
      <Input
        ref={ref}
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]*"
        maxLength={6}
        className={cn("h-14 text-center font-mono text-2xl tracking-[0.5em]", className)}
        onChange={(event) => {
          event.target.value = event.target.value.replace(/\D/g, "").slice(0, 6);
          onChange?.(event);
        }}
        {...props}
      />
    );
  },
);
