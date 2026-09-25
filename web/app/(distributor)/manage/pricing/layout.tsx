import type { ReactNode } from "react";

import { PricingLayout } from "@/components/pricing/pricing-nav";

export default function Layout({ children }: { children: ReactNode }) {
  return <PricingLayout>{children}</PricingLayout>;
}
