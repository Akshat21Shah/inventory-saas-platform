import { EditDiscountRulePage } from "@/components/pricing/discounts";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EditDiscountRulePage ruleId={id} />;
}
