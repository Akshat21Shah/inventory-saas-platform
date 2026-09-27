import { Suspense } from "react";

import { PageSkeleton } from "@/components/shared/skeletons";
import { ReceiptsPage } from "@/components/stock/receipts";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ReceiptsPage />
    </Suspense>
  );
}
