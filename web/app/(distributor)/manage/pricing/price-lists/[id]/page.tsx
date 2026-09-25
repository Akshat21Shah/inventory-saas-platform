import { PriceListDetailPage } from "@/components/pricing/price-lists";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PriceListDetailPage priceListId={id} />;
}
