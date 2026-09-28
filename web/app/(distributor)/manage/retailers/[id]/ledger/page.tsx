import { RetailerLedgerPage } from "@/components/billing/receivables";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RetailerLedgerPage retailerId={id} />;
}
