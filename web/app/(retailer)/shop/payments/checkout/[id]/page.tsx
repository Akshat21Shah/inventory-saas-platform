import { ShopCheckoutPage } from "@/components/shop/pay";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ShopCheckoutPage intentId={id} />;
}
