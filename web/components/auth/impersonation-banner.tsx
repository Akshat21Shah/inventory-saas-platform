"use client";

import { Eye, PenLine, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState, type FormEvent } from "react";

import { FormField } from "@/components/shared/form-field";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { authImpersonationAct } from "@/lib/api/generated/endpoints/auth/auth";
import { useErrorText } from "@/lib/api/use-error-text";

import { useAuth } from "./auth-provider";

function useMinutesLeft(expiresAt: string | undefined): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, []);
  return expiresAt ? Math.max(0, Math.ceil((Date.parse(expiresAt) - now) / 60_000)) : 0;
}

/** Persistent while a super admin acts as this user (ADR-029). Everything here is audited. */
export function ImpersonationBanner() {
  const t = useTranslations("impersonation");
  const errors = useErrorText();
  const { me, signIn, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const minutes = useMinutesLeft(me?.impersonation?.expires_at);
  if (!me?.impersonation) return null;
  const acting = me.impersonation.mode === "ACT";
  const who = me.full_name || me.email || me.phone || "";

  async function enableAct(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const response = await authImpersonationAct({ reason });
      await signIn(response.data.access, response.data.access_expires_at);
      setOpen(false);
    } catch (err) {
      setError(errors.message(err));
    }
  }

  return (
    <div
      role="status"
      className="bg-warning/20 text-warning-strong border-warning/40 sticky top-0 z-40 flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-2 text-sm"
    >
      <span className="flex items-center gap-2 font-medium">
        {acting ? (
          <PenLine aria-hidden className="size-4" />
        ) : (
          <Eye aria-hidden className="size-4" />
        )}
        {t(acting ? "actingAs" : "viewingAs", { name: who })}
      </span>
      <span>{t("minutesLeft", { minutes })}</span>
      <span className="ml-auto flex gap-2">
        {!acting ? (
          <Button size="sm" variant="outline" className="min-h-9" onClick={() => setOpen(true)}>
            {t("switchToAct")}
          </Button>
        ) : null}
        <Button
          size="sm"
          className="min-h-9"
          onClick={async () => {
            await signOut();
            window.close();
          }}
        >
          <X aria-hidden />
          {t("end")}
        </Button>
      </span>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <form onSubmit={enableAct} className="space-y-4">
            <DialogHeader>
              <DialogTitle>{t("actTitle")}</DialogTitle>
              <DialogDescription>{t("actBody")}</DialogDescription>
            </DialogHeader>
            <FormField label={t("reason")} error={error ?? undefined} required>
              <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} />
            </FormField>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                {t("cancel")}
              </Button>
              <Button type="submit" disabled={!reason.trim()}>
                {t("confirmAct")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
