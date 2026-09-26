import { Suspense } from "react";

import { NewDiscountRulePage } from "@/components/pricing/discounts";
import { PageSkeleton } from "@/components/shared/skeletons";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <NewDiscountRulePage />
    </Suspense>
  );
}
