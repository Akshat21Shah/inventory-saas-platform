"use client";

import { formatCompact } from "@/lib/format";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatMoney } from "@/lib/format";

import type { ReportRow } from "./cells";

/**
 * Net sales per period (the sales summary's rows on this page) as bars. A picture only: the same
 * figures are in the table right below it, so it is hidden from screen readers. Values arrive as
 * the server's strings and become numbers only to draw.
 */
export function PeriodChart({
  rows,
  labelKey,
  valueKey,
  caption,
}: {
  rows: ReportRow[];
  labelKey: string;
  valueKey: string;
  caption: string;
}) {
  const bars = rows.map((row) => ({
    label: String(row[labelKey] ?? ""),
    value: Number(row[valueKey] ?? 0),
    text: String(row[valueKey] ?? "0"),
  }));
  return (
    <figure className="m-0 rounded-xl border p-3" aria-hidden>
      <figcaption className="text-muted-foreground mb-2 text-sm">{caption}</figcaption>
      <div className="h-48 w-full">
        <ResponsiveContainer
          width="100%"
          height="100%"
          initialDimension={{ width: 320, height: 192 }}
        >
          <BarChart data={bars} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 12, fill: "var(--muted-foreground)" }}
              tickLine={false}
              axisLine={false}
              minTickGap={16}
            />
            <YAxis
              tickFormatter={(n: number) => formatCompact(n)}
              tick={{ fontSize: 12, fill: "var(--muted-foreground)" }}
              tickLine={false}
              axisLine={false}
              width={44}
            />
            <Tooltip
              formatter={(_n, _name, item) => [formatMoney(String(item.payload.text)), caption]}
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                color: "var(--popover-foreground)",
              }}
            />
            <Bar
              dataKey="value"
              fill="var(--primary)"
              radius={[4, 4, 0, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
