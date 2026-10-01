import { Suspense } from "react";

import { PurchaseOrdersPage } from "@/components/purchasing/purchase-orders";
import { PageSkeleton } from "@/components/shared/skeletons";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <PurchaseOrdersPage />
    </Suspense>
  );
}
