import { Suspense } from "react";

import { PageSkeleton } from "@/components/shared/skeletons";
import { AdjustmentEditor } from "@/components/stock/adjustments";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <AdjustmentEditor />
    </Suspense>
  );
}
