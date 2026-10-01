import { Suspense } from "react";

import { OrdersBoard } from "@/components/orders/board";
import { PageSkeleton } from "@/components/shared/skeletons";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <OrdersBoard />
    </Suspense>
  );
}
