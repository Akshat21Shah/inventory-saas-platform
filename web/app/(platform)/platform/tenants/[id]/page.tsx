import { TenantDetail } from "@/components/platform/tenant-detail";

export default async function TenantPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <TenantDetail tenantId={id} />;
}
