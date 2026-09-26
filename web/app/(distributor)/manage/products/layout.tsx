import type { ReactNode } from "react";

import { CatalogLayout } from "@/components/catalog/catalog-nav";

export default function Layout({ children }: { children: ReactNode }) {
  return <CatalogLayout>{children}</CatalogLayout>;
}
