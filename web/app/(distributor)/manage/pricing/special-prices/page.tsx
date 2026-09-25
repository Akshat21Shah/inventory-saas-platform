import { Suspense } from "react";

import { SpecialPricesPage } from "@/components/pricing/special-prices";
import { PageSkeleton } from "@/components/shared/skeletons";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <SpecialPricesPage />
    </Suspense>
  );
}
