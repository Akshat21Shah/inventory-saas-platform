import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginScreen } from "@/components/auth/login-screen";
import { PageSkeleton } from "@/components/shared/skeletons";
import { getTranslations } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("auth"))("signInTitle") };
}

export default function LoginPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <LoginScreen />
    </Suspense>
  );
}
