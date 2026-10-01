import { ReportViewer } from "@/components/reports/viewer";

export default async function Page({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  return <ReportViewer code={code} />;
}
