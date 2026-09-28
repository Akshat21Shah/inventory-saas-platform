import { CreditNoteDetailPage } from "@/components/billing/credit-notes";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CreditNoteDetailPage noteId={id} />;
}
