import type { ReactNode } from "react";

import { StockLayout } from "@/components/stock/stock-nav";

export default function Layout({ children }: { children: ReactNode }) {
  return <StockLayout>{children}</StockLayout>;
}
