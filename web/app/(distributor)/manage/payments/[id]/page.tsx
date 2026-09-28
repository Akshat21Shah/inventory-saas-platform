import { PaymentDetailPage } from "@/components/billing/payments";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PaymentDetailPage paymentId={id} />;
}
