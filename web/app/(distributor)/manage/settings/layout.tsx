import type { ReactNode } from "react";

import { SettingsLayout } from "@/components/distributor/settings-nav";

export default function Layout({ children }: { children: ReactNode }) {
  return <SettingsLayout>{children}</SettingsLayout>;
}
