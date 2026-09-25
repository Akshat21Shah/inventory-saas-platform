import { SettingsLayout } from "@/components/distributor/settings-nav";
import { TenantAuditPage } from "@/components/distributor/staff";

export default function Page() {
  return (
    <SettingsLayout>
      <TenantAuditPage />
    </SettingsLayout>
  );
}
