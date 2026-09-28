import { Suspense } from "react";

import { NewPaymentPage } from "@/components/billing/payments";

export default function Page() {
  return (
    <Suspense>
      <NewPaymentPage />
    </Suspense>
  );
}
