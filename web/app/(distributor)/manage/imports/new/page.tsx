import { Suspense } from "react";

import { ImportStartPage } from "@/components/imports/import-wizard";
import { PageSkeleton } from "@/components/shared/skeletons";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ImportStartPage />
    </Suspense>
  );
}
