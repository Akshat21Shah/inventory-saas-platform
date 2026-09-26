import { Suspense } from "react";

import { PageSkeleton } from "@/components/shared/skeletons";
import { ReceiptPage } from "@/components/stock/receipts";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ReceiptPage receiptId={id} />
    </Suspense>
  );
}
