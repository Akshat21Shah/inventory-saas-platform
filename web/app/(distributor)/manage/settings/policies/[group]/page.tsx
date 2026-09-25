import { PolicySettings } from "@/components/distributor/policy-settings";

export default async function Page({ params }: { params: Promise<{ group: string }> }) {
  const { group } = await params;
  return <PolicySettings group={group} />;
}
