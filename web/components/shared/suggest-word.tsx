"use client";

import { Languages } from "lucide-react";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

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
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { textsSuggestionsCreate } from "@/lib/api/generated/endpoints/texts/texts";
import { useErrorText } from "@/lib/api/use-error-text";
import { defaultLocale, languageOf } from "@/lib/i18n/config";
import { cn } from "@/lib/utils";

/** Words selected on the page when the link was used, to start the form with. */
export function selectedWords(): string {
  if (typeof window === "undefined") return "";
  return (window.getSelection()?.toString() ?? "").replace(/\s+/g, " ").trim().slice(0, 500);
}

/** Whether to offer the link: only on screens in a translated language (English is the source). */
export function useOffersSuggestions(): boolean {
  return languageOf(useLocale()) !== defaultLocale;
}

/**
 * "Suggest a better word" (ADR-060 item 14): staff and shops send a better translation from any
 * screen; the screen, the words, the language and the suggestion go to the super admin's list.
 */
export function SuggestWordDialog({
  open,
  onOpenChange,
  words,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  words: string;
}) {
  const t = useTranslations("suggestWord");
  const screen = usePathname();
  const language = languageOf(useLocale());
  const errors = useErrorText();
  const [current, setCurrent] = useState(words);
  const [better, setBetter] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [shownFor, setShownFor] = useState(open);
  // Start each opening with the words selected on the page (react.dev: adjusting state on a
  // prop change while rendering).
  if (open !== shownFor) {
    setShownFor(open);
    if (open) {
      setCurrent(words);
      setBetter("");
      setFieldErrors({});
    }
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFieldErrors({});
    try {
      await textsSuggestionsCreate({
        language,
        screen,
        current_text: current.trim(),
        suggestion: better.trim(),
      });
      toast.success(t("thanks"));
      onOpenChange(false);
    } catch (err) {
      const byField = errors.fields(err);
      setFieldErrors(byField);
      if (!Object.keys(byField).length) toast.error(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={send} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{t("title")}</DialogTitle>
            <DialogDescription>{t("body")}</DialogDescription>
          </DialogHeader>
          <FormField label={t("current")} hint={t("currentHint")} error={fieldErrors.current_text}>
            <Input
              className="h-10"
              value={current}
              maxLength={500}
              onChange={(e) => setCurrent(e.target.value)}
              lang={language}
            />
          </FormField>
          <FormField label={t("better")} error={fieldErrors.suggestion} required>
            <Textarea
              value={better}
              rows={3}
              maxLength={500}
              onChange={(e) => setBetter(e.target.value)}
              lang={language}
              required
            />
          </FormField>
          <DialogFooter>
            <Button type="submit" className="min-h-10" disabled={busy || !better.trim()}>
              {t("send")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** A small "Suggest a better word" link that opens the form (shown on translated screens). */
export function SuggestWordLink({ className }: { className?: string }) {
  const t = useTranslations("suggestWord");
  const offers = useOffersSuggestions();
  const [open, setOpen] = useState(false);
  const [words, setWords] = useState("");
  if (!offers) return null;
  return (
    <>
      <button
        type="button"
        // Read the selection before the button takes the focus.
        onPointerDown={() => setWords(selectedWords())}
        onClick={() => {
          setOpen(true);
        }}
        className={cn(
          "text-muted-foreground inline-flex min-h-10 items-center gap-1 text-xs underline-offset-4 hover:underline max-md:min-h-11",
          className,
        )}
      >
        <Languages aria-hidden className="size-3.5" />
        {t("link")}
      </button>
      <SuggestWordDialog open={open} onOpenChange={setOpen} words={words} />
    </>
  );
}
