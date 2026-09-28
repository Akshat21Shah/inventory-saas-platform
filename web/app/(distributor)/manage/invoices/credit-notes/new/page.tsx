import { Suspense } from "react";

import { NewCreditNotePage } from "@/components/billing/credit-notes";

export default function Page() {
  return (
    <Suspense>
      <NewCreditNotePage />
    </Suspense>
  );
}
