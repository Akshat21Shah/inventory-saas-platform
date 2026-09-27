import { Suspense } from "react";

import { PageSkeleton } from "@/components/shared/skeletons";
import { ReceiptEditor } from "@/components/stock/receipt-editor";

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ReceiptEditor />
    </Suspense>
  );
}
