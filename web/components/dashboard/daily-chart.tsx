"use client";

import { useLocale } from "next-intl";

import { formatCompact, formatDayMonth } from "@/lib/format";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface DailySeries {
  key: string;
  label: string;
  /** A CSS colour, e.g. a design token: `var(--primary)`. */
  color: string;
  dashed?: boolean;
  /** How a value reads in the tooltip and the table (money from the server's string). */
  format: (value: string) => string;
}

/**
 * A value per day as lines (one per series), for the dashboards. The chart is a picture; screen
 * readers get its caption and the same figures as a table. Values arrive as the server's
 * strings: they are turned into numbers only to draw (no sums are made here).
 */
export function DailyChart({
  rows,
  series,
  caption,
  dateLabel,
}: {
  rows: readonly { date: string }[];
  series: DailySeries[];
  caption: string;
  dateLabel: string;
}) {
  const locale = useLocale();
  const day = (value: string) => formatDayMonth(value, locale);
  const value = (row: { date: string }, key: string) =>
    String((row as unknown as Record<string, unknown>)[key] ?? "");
  const points = rows.map((row) => ({
    date: row.date,
    ...Object.fromEntries(series.map((s) => [s.key, Number(value(row, s.key) || 0)])),
  }));
  return (
    <figure className="m-0">
      <figcaption className="sr-only">{caption}</figcaption>
      <div aria-hidden className="h-56 w-full sm:h-64">
        <ResponsiveContainer
          width="100%"
          height="100%"
          initialDimension={{ width: 320, height: 224 }}
        >
          <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={day}
              tick={{ fontSize: 12, fill: "var(--muted-foreground)" }}
              tickLine={false}
              axisLine={false}
              minTickGap={24}
            />
            <YAxis
              tickFormatter={(value: number) => formatCompact(value)}
              tick={{ fontSize: 12, fill: "var(--muted-foreground)" }}
              tickLine={false}
              axisLine={false}
              width={44}
            />
            <Tooltip
              labelFormatter={(value) => day(String(value))}
              formatter={(value, name) => {
                const s = series.find((one) => one.key === name);
                return [s ? s.format(String(value)) : String(value), s?.label ?? String(name)];
              }}
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                color: "var(--popover-foreground)",
              }}
            />
            {series.map((s) => (
              <Line
                key={s.key}
                type="linear"
                dataKey={s.key}
                name={s.key}
                stroke={s.color}
                strokeWidth={2}
                strokeDasharray={s.dashed ? "4 4" : undefined}
                dot={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <ul aria-hidden className="text-muted-foreground mt-2 flex flex-wrap gap-4 text-xs">
        {series.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <span
              className="inline-block h-0.5 w-4"
              style={{
                background: s.dashed
                  ? `repeating-linear-gradient(90deg, ${s.color} 0 4px, transparent 4px 8px)`
                  : s.color,
              }}
            />
            {s.label}
          </li>
        ))}
      </ul>
      {/* In a wrapper: a table ignores sr-only's 1px width and would widen the page. */}
      <div className="sr-only">
        <table>
          <caption>{caption}</caption>
          <thead>
            <tr>
              <th scope="col">{dateLabel}</th>
              {series.map((s) => (
                <th key={s.key} scope="col">
                  {s.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.date}>
                <th scope="row">{day(row.date)}</th>
                {series.map((s) => (
                  <td key={s.key}>{s.format(value(row, s.key))}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}
