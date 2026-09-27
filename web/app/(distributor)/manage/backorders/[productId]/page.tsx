import { BackorderProductPage } from "@/components/orders/backorders";

export default async function Page({ params }: { params: Promise<{ productId: string }> }) {
  const { productId } = await params;
  return <BackorderProductPage productId={productId} />;
}
