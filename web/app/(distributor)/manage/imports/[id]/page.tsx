import { ImportJobPage } from "@/components/imports/import-wizard";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ImportJobPage jobId={id} />;
}
