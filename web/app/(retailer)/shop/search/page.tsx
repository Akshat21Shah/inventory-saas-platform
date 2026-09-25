import { Suspense } from "react";

import { PageSkeleton } from "@/components/shared/skeletons";
import { SearchPage } from "@/components/shop/catalog";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <SearchPage />
    </Suspense>
  );
}
