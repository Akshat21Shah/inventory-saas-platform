"use client";

import { useTranslations } from "@/lib/i18n/translations";
import { cn } from "@/lib/utils";

/** A hint only; the server's password rules decide (Django validators). */
export function passwordScore(password: string): 0 | 1 | 2 | 3 {
  if (password.length < 10) return 0;
  const variety = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(password)).length;
  if (password.length >= 14 && variety >= 3) return 3;
  if (password.length >= 12 || variety >= 3) return 2;
  return 1;
}

export function PasswordStrength({ password }: { password: string }) {
  const t = useTranslations("auth.strength");
  const score = password ? passwordScore(password) : null;
  if (score === null) return <p className="text-muted-foreground text-xs">{t("hint")}</p>;
  const label = ["tooShort", "fair", "good", "strong"][score] as
    "tooShort" | "fair" | "good" | "strong";
  return (
    <div className="space-y-1" aria-live="polite">
      <div className="flex gap-1" aria-hidden>
        {[1, 2, 3].map((step) => (
          <span
            key={step}
            className={cn("h-1.5 flex-1 rounded-full", score >= step ? "bg-primary" : "bg-muted")}
          />
        ))}
      </div>
      <p className="text-muted-foreground text-xs">{t(label)}</p>
    </div>
  );
}
