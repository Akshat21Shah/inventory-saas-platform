import { Suspense } from "react";

import { OrderOnBehalfPage } from "@/components/orders/on-behalf";
import { PageSkeleton } from "@/components/shared/skeletons";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <OrderOnBehalfPage />
    </Suspense>
  );
}
