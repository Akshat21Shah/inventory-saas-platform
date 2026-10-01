import { Suspense } from "react";

import { SuppliersPage } from "@/components/purchasing/suppliers";
import { PageSkeleton } from "@/components/shared/skeletons";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <SuppliersPage />
    </Suspense>
  );
}
