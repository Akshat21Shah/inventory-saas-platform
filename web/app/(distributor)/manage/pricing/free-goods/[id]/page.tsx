import { EditFreeGoodsPage } from "@/components/pricing/free-goods";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EditFreeGoodsPage schemeId={id} />;
}
