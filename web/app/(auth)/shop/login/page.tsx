import type { Metadata } from "next";
import { getTranslations } from "@/lib/i18n/server";
import { Suspense } from "react";

import { ShopLoginScreen } from "@/components/auth/login-screen";
import { PageSkeleton } from "@/components/shared/skeletons";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("auth"))("retailer.title") };
}

export default function ShopLoginPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ShopLoginScreen />
    </Suspense>
  );
}
