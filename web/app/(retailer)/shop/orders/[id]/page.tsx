import { Suspense } from "react";

import { PageSkeleton } from "@/components/shared/skeletons";
import { OrderPage } from "@/components/shop/orders";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense fallback={<PageSkeleton />}>
      <OrderPage orderId={id} />
    </Suspense>
  );
}
