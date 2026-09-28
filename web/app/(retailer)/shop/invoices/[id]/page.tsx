import { ShopBillPage } from "@/components/shop/account";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ShopBillPage invoiceId={id} />;
}
