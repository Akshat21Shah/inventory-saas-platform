import { StockDetailPage } from "@/components/stock/stock-detail";

export default async function Page({ params }: { params: Promise<{ productId: string }> }) {
  const { productId } = await params;
  return <StockDetailPage productId={productId} />;
}
