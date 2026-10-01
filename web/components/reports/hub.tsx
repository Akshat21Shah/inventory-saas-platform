"use client";

import {
  Banknote,
  Boxes,
  Download,
  FileSpreadsheet,
  TrendingUp,
  Truck,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { PageHeader } from "@/components/shared/page-header";
import { CardSkeleton } from "@/components/shared/skeletons";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useReportsCatalogue } from "@/lib/api/generated/endpoints/reports/reports";

import { useReportWords } from "./words";

const GROUPS: [string, LucideIcon][] = [
  ["sales", TrendingUp],
  ["stock", Boxes],
  ["money", Banknote],
  ["gst", FileSpreadsheet],
  ["purchasing", Truck],
];

/** Reports with a screen of their own from before the framework (Phase 3), richer than the
 * standard one: they keep it. */
const OWN_PAGES: Record<string, string> = {
  low_stock: "/manage/reports/low-stock",
  stock_valuation: "/manage/reports/stock-valuation",
};

export function reportHref(code: string): string {
  return OWN_PAGES[code] ?? `/manage/reports/${code}`;
}

/** Every report this person may open, by group (the server decides which: ADR-050 item 2). */
export function ReportsHub() {
  const t = useTranslations("reports.hub");
  const words = useReportWords();
  const catalogue = useReportsCatalogue();
  const reports = catalogue.data?.data ?? [];
  const groups = GROUPS.map(([group, icon]) => ({
    group,
    icon,
    reports: reports.filter((r) => r.group === group),
  })).filter((g) => g.reports.length);
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Button asChild variant="outline" className="min-h-10">
            <Link href="/manage/reports/exports">
              <Download aria-hidden />
              {t("myExports")}
            </Link>
          </Button>
        }
      />
      {catalogue.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : catalogue.error ? (
        <ErrorState error={catalogue.error} onRetry={() => void catalogue.refetch()} />
      ) : groups.length === 0 ? (
        <EmptyState title={t("empty")} description={t("emptyBody")} />
      ) : (
        <div className="space-y-8">
          {groups.map(({ group, icon: Icon, reports: listed }) => (
            <section key={group} aria-labelledby={`reports-${group}`} className="space-y-3">
              <h2 id={`reports-${group}`} className="flex items-center gap-2 text-lg font-semibold">
                <Icon aria-hidden className="text-primary size-5" />
                {words.group(group)}
              </h2>
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {listed.map((report) => (
                  <li key={report.code}>
                    <Link
                      href={reportHref(report.code)}
                      className="block h-full rounded-xl focus-visible:ring-2"
                    >
                      <Card className="hover:bg-muted h-full transition-colors">
                        <CardContent className="space-y-1 py-4">
                          <span className="block font-semibold">
                            {words.title(report.code, report.title)}
                          </span>
                          <span className="text-muted-foreground block text-sm">
                            {words.description(report.code, report.description)}
                          </span>
                        </CardContent>
                      </Card>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
