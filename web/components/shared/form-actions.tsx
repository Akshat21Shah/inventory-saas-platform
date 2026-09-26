import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Save / Cancel for a long form. Phones: a bar stuck to the bottom of the screen, so the buttons
 * are always in reach. Wider screens: a normal row at the end of the form (CLAUDE.md "Responsive
 * design").
 */
export function FormActions({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      data-slot="form-actions"
      className={cn(
        "flex items-center justify-end gap-2",
        "max-md:bg-background/95 max-md:sticky max-md:bottom-0 max-md:z-20 max-md:-mx-4 max-md:border-t max-md:px-4 max-md:py-3 max-md:backdrop-blur max-md:[&>*]:flex-1",
        className,
      )}
    >
      {children}
    </div>
  );
}
