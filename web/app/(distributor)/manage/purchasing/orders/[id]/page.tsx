import { PurchaseOrderPage } from "@/components/purchasing/purchase-orders";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PurchaseOrderPage orderId={id} />;
}
