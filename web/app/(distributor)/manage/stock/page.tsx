import { Suspense } from "react";

import { PageSkeleton } from "@/components/shared/skeletons";
import { StockPage } from "@/components/stock/stock-page";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <StockPage />
    </Suspense>
  );
}
