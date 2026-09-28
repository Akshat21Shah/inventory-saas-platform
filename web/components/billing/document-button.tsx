"use client";

import { Download } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import type { DocumentLink } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";

/** Opens a printed document (invoice, credit note, receipt, voucher, confirmation). The server
 * answers with a short-lived link, or "being prepared" (202) while the PDF is printed. A window
 * is opened on the click itself so browsers don't block it, then pointed at the link. */
export function DocumentButton({
  fetchLink,
  children,
  variant = "outline",
}: {
  fetchLink: () => Promise<{ data: DocumentLink; status: number }>;
  children: ReactNode;
  variant?: "outline" | "default" | "ghost";
}) {
  const t = useTranslations("billing.document");
  const { message } = useErrorText();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant={variant}
      className="min-h-10 gap-2"
      disabled={busy}
      onClick={async () => {
        const target = window.open("", "_blank");
        setBusy(true);
        try {
          const { data } = await fetchLink();
          if (data.status === "READY" && data.url) {
            if (target) target.location.href = data.url;
            else window.location.assign(data.url);
            return;
          }
          target?.close();
          toast.info(data.status === "FAILED" ? t("failed") : t("preparing"));
        } catch (error) {
          target?.close();
          toast.error(message(error));
        } finally {
          setBusy(false);
        }
      }}
    >
      <Download aria-hidden className="size-4" />
      {children}
    </Button>
  );
}
