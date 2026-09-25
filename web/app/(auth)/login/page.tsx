import { LogIn } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/shared/empty-state";

export default async function LoginPage() {
  const t = await getTranslations("auth");
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center px-4">
      <EmptyState icon={LogIn} title={t("signInTitle")} description={t("signInPending")} />
    </main>
  );
}
