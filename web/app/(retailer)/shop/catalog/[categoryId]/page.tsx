import { CatalogPage } from "@/components/shop/catalog";

export default async function Page({ params }: { params: Promise<{ categoryId: string }> }) {
  const { categoryId } = await params;
  return <CatalogPage key={categoryId} categoryId={categoryId} />;
}
