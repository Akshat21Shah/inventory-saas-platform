import { Suspense } from "react";

import { NewRefundPage } from "@/components/billing/refunds";

export default function Page() {
  return (
    <Suspense>
      <NewRefundPage />
    </Suspense>
  );
}
