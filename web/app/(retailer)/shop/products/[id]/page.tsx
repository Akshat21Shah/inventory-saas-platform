import { ProductPage } from "@/components/shop/catalog";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ProductPage productId={id} />;
}
