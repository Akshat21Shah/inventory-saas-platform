import { Suspense } from "react";

import { CreditNotesPage } from "@/components/billing/credit-notes";
import { PageSkeleton } from "@/components/shared/skeletons";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <CreditNotesPage />
    </Suspense>
  );
}
