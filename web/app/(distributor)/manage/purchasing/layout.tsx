import type { ReactNode } from "react";

import { PurchasingLayout } from "@/components/purchasing/purchasing-nav";

export default function Layout({ children }: { children: ReactNode }) {
  return <PurchasingLayout>{children}</PurchasingLayout>;
}
