import { Suspense } from "react";

import { InvoicesPage } from "@/components/billing/invoices";
import { PageSkeleton } from "@/components/shared/skeletons";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <InvoicesPage />
    </Suspense>
  );
}
