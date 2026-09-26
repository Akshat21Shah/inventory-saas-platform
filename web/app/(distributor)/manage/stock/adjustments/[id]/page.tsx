import { AdjustmentPage } from "@/components/stock/adjustments";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AdjustmentPage adjustmentId={id} />;
}
