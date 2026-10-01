import { SupplierPage } from "@/components/purchasing/suppliers";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SupplierPage supplierId={id} />;
}
