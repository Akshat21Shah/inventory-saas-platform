"use client";

import { SlidersHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { useIsPhone } from "@/lib/use-media";

/**
 * A list's search and filters. Laptops and tablets: all inline. Phones: the search stays visible
 * and the filters open in a bottom sheet from a "Filters (n)" button (CLAUDE.md "Responsive
 * design").
 */
export function FilterBar({
  search,
  filters,
  active,
  onClear,
}: {
  search?: ReactNode;
  filters: ReactNode;
  /** How many filters differ from their default (shown on the button). */
  active: number;
  onClear?: () => void;
}) {
  const t = useTranslations("filters");
  const phone = useIsPhone();
  const [open, setOpen] = useState(false);
  if (!phone) {
    return (
      <>
        {search}
        {filters}
      </>
    );
  }
  return (
    <div className="flex w-full items-center gap-2">
      <div className="min-w-0 flex-1 [&>*]:w-full">{search}</div>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button variant="outline" className="min-h-11 shrink-0">
            <SlidersHorizontal aria-hidden />
            {active ? t("buttonActive", { count: active }) : t("button")}
          </Button>
        </SheetTrigger>
        <SheetContent side="bottom" className="max-h-[85dvh] overflow-y-auto rounded-t-2xl p-4">
          <SheetHeader className="p-0">
            <SheetTitle>{t("title")}</SheetTitle>
            <SheetDescription className="sr-only">{t("description")}</SheetDescription>
          </SheetHeader>
          <div className="flex flex-col gap-3 [&_button[role=combobox]]:w-full [&>*]:w-full">
            {filters}
          </div>
          <SheetFooter className="flex-row gap-2 p-0">
            {onClear && active ? (
              <Button variant="outline" className="min-h-11 flex-1" onClick={onClear}>
                {t("clear")}
              </Button>
            ) : null}
            <Button className="min-h-11 flex-1" onClick={() => setOpen(false)}>
              {t("show")}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </div>
  );
}
