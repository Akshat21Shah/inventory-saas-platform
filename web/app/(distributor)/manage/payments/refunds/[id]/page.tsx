import { RefundDetailPage } from "@/components/billing/refunds";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RefundDetailPage refundId={id} />;
}
