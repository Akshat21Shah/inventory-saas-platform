import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

export function KpiCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number | string;
  icon?: LucideIcon;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 py-5">
        {Icon ? (
          <span className="bg-brand-50 text-primary flex size-10 items-center justify-center rounded-lg">
            <Icon aria-hidden className="size-5" />
          </span>
        ) : null}
        <div>
          <p className="text-muted-foreground text-sm">{label}</p>
          <p className="text-2xl font-semibold tabular-nums">{value}</p>
        </div>
      </CardContent>
    </Card>
  );
}
