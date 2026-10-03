"use client";

import { Languages } from "lucide-react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePublicLanguages } from "@/lib/api/generated/endpoints/public/public";
import { hasLanguageCookie, pickLanguage, rememberLanguage } from "@/lib/i18n/client";
import { languageOf } from "@/lib/i18n/config";

import { useHostBranding } from "./tenant-branding";

/**
 * The sign-in pages' language (ADR-060 item 2): on a distributor's address, the languages its
 * people may use; on the super admin's, every language (super admins may use any); elsewhere, the
 * languages on for everyone. A shop's sign-in opens in the distributor's language for shops until
 * someone picks. The pick is saved to the person's profile once they sign in.
 */
export function SignInLanguage({ shopDefault = false }: { shopDefault?: boolean }) {
  const t = useTranslations("auth");
  const router = useRouter();
  const current = languageOf(useLocale());
  const { hostKind, branding } = useHostBranding();
  const every = usePublicLanguages({ query: { enabled: hostKind !== "TENANT" } });
  const options =
    hostKind === "TENANT"
      ? (branding?.languages ?? [])
      : (every.data?.data ?? []).filter((row) => hostKind === "ADMIN" || row.enabled);

  useEffect(() => {
    if (!shopDefault || !branding || hasLanguageCookie()) return;
    if (rememberLanguage(branding.default_language)) router.refresh();
  }, [shopDefault, branding, router]);

  if (options.length < 2) return null;
  return (
    <Select
      value={current}
      onValueChange={(code) => {
        if (pickLanguage(code)) router.refresh();
      }}
    >
      <SelectTrigger aria-label={t("language")} className="min-h-10 w-auto gap-2">
        <Languages aria-hidden className="size-4" />
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.code} value={option.code} lang={option.code}>
            {option.native}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
