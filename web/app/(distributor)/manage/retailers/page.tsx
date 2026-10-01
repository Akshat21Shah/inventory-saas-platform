import { Suspense } from "react";

import { RetailersPage } from "@/components/retailers/retailers-page";
import { PageSkeleton } from "@/components/shared/skeletons";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <RetailersPage />
    </Suspense>
  );
}
