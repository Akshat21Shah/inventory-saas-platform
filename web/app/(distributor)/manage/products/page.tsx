import { Suspense } from "react";

import { ProductsPage } from "@/components/catalog/products-page";
import { PageSkeleton } from "@/components/shared/skeletons";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ProductsPage />
    </Suspense>
  );
}
