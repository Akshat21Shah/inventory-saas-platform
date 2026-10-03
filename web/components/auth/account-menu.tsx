"use client";

import { ChevronsUpDown, Languages, LogOut, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import {
  SuggestWordDialog,
  selectedWords,
  useOffersSuggestions,
} from "@/components/shared/suggest-word";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { useAuth } from "./auth-provider";

/** Who is signed in, a link to their account page, "Suggest a better word" on translated
 * screens, and sign out. */
export function AccountMenu({ accountHref }: { accountHref: string }) {
  const t = useTranslations("auth");
  const { me, signOut } = useAuth();
  const router = useRouter();
  const offers = useOffersSuggestions();
  const [suggesting, setSuggesting] = useState(false);
  const [words, setWords] = useState("");
  if (!me) return null;
  const name = me.full_name || me.email || me.phone || "";
  return (
    <>
      <DropdownMenu
        onOpenChange={(open) => {
          if (open) setWords(selectedWords()); // before the menu takes the focus
        }}
      >
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" className="h-11 w-full justify-between gap-2 px-2 md:w-full">
            <span className="flex min-w-0 items-center gap-2">
              <UserRound aria-hidden className="size-4 shrink-0" />
              <span className="truncate text-sm">{name}</span>
            </span>
            <ChevronsUpDown aria-hidden className="size-4 opacity-60" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuLabel className="truncate">{me.tenant?.name ?? name}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem asChild>
            <Link href={accountHref}>{t("myAccount")}</Link>
          </DropdownMenuItem>
          {offers ? (
            <DropdownMenuItem onSelect={() => setSuggesting(true)}>
              <Languages aria-hidden />
              {t("suggestWord")}
            </DropdownMenuItem>
          ) : null}
          <DropdownMenuItem
            onSelect={async () => {
              await signOut();
              router.replace(me.user_type === "RETAILER" ? "/shop/login" : "/login");
            }}
          >
            <LogOut aria-hidden />
            {t("signOut")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <SuggestWordDialog open={suggesting} onOpenChange={setSuggesting} words={words} />
    </>
  );
}
