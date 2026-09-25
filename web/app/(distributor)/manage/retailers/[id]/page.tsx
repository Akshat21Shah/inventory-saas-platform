import { RetailerDetailPage } from "@/components/retailers/retailer-editor";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RetailerDetailPage retailerId={id} />;
}
