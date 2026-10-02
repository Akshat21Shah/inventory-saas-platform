import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A message from an outside service (the GST provider, the payment gateway, an email, SMS or
 * WhatsApp service): a line in the person's language saying what failed, then the service's own
 * words exactly as they came, in English (owner, ADR-060). For failures of our own there are no
 * service's words: only the line shows. Spans, so it fits inside a paragraph or a table cell.
 */
export function ProviderMessage({
  line,
  message,
  compact = false,
  className,
}: {
  line: ReactNode;
  message?: string | null;
  compact?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("block space-y-0.5", className)}>
      <span className="block">{line}</span>
      {message ? (
        <span
          lang="en"
          dir="ltr"
          className={cn("block break-words opacity-80", compact ? "text-xs" : "text-sm")}
        >
          {message}
        </span>
      ) : null}
    </span>
  );
}
