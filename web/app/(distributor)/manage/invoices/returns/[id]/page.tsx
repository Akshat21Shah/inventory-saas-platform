import { ReturnRequestPage } from "@/components/billing/returns";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReturnRequestPage requestId={id} />;
}
