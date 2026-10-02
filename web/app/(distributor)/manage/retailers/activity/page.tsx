import { Suspense } from "react";

import { ShopActivityPage } from "@/components/insights/shop-activity";
import { PageSkeleton } from "@/components/shared/skeletons";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ShopActivityPage />
    </Suspense>
  );
}
