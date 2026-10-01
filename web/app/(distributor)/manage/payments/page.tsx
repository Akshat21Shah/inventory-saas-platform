import { Suspense } from "react";

import { PaymentsPage } from "@/components/billing/payments";
import { PageSkeleton } from "@/components/shared/skeletons";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <PaymentsPage />
    </Suspense>
  );
}
