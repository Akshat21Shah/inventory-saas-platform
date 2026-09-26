import { Suspense } from "react";

import { PageSkeleton } from "@/components/shared/skeletons";
import { AdjustmentsPage } from "@/components/stock/adjustments";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <AdjustmentsPage />
    </Suspense>
  );
}
