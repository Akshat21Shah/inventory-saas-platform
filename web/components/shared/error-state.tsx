"use client";

import { RefreshCw, TriangleAlert } from "lucide-react";
import { useMessages } from "next-intl";

import { Button } from "@/components/ui/button";
import { errorMessageKey } from "@/lib/api/errors";
import { useTranslations } from "@/lib/i18n/translations";
import { cn } from "@/lib/utils";

interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}

/** Friendly error with retry. Maps API error codes to translated text; never shows raw errors. */
export function ErrorState({ error, onRetry, className }: ErrorStateProps) {
  const t = useTranslations();
  const messages = useMessages() as { errors?: Record<string, string> };
  const knownCodes = new Set(Object.keys(messages.errors ?? {}));
  return (
    <div
      role="alert"
      className={cn(
        "border-destructive/30 bg-destructive/5 flex flex-col items-center gap-3 rounded-xl border px-6 py-10 text-center",
        className,
      )}
    >
      <TriangleAlert aria-hidden className="text-destructive size-8" />
      <div className="space-y-1">
        <h3 className="text-base font-semibold">{t("errors.title")}</h3>
        <p className="text-muted-foreground text-sm">{t(errorMessageKey(error, knownCodes))}</p>
      </div>
      {onRetry ? (
        <Button variant="outline" onClick={onRetry} className="min-h-11">
          <RefreshCw aria-hidden />
          {t("common.retry")}
        </Button>
      ) : null}
    </div>
  );
}
