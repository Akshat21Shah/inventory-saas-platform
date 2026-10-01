import { Suspense } from "react";

import { EditPurchaseOrderPage } from "@/components/purchasing/purchase-orders";
import { PageSkeleton } from "@/components/shared/skeletons";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense fallback={<PageSkeleton />}>
      <EditPurchaseOrderPage orderId={id} />
    </Suspense>
  );
}
