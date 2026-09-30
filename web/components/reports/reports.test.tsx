import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Report, ReportPage, ReportRun } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { MyExports } from "./exports";
import { ReportsHub } from "./hub";
import { ReportViewer } from "./viewer";

const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("sonner", () => ({ toast }));
const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/manage/reports",
  useSearchParams: () => new URLSearchParams(),
}));

const byProduct: Report = {
  code: "sales_by_product",
  title: "Sales by product",
  group: "sales",
  description: "Server description",
  pdf: false,
  background_only: false,
  max_days: 366,
  own_shops: false,
  columns: [
    { key: "code", label: "Code", kind: "text", cost: false, total: false },
    { key: "name", label: "Product", kind: "text", cost: false, total: false },
    { key: "qty", label: "Quantity", kind: "qty", cost: false, total: true },
    { key: "total", label: "Total", kind: "money", cost: false, total: true },
  ],
  filters: [
    {
      key: "date_from",
      label: "From",
      kind: "date",
      required: true,
      choices: [],
      default: "2026-09-01",
      entity: "",
    },
    {
      key: "date_to",
      label: "To",
      kind: "date",
      required: true,
      choices: [],
      default: "2026-09-30",
      entity: "",
    },
    {
      key: "group_by",
      label: "By",
      kind: "choice",
      required: false,
      choices: ["week", "month"],
      default: null,
      entity: "",
    },
  ],
};
const lowStock: Report = { ...byProduct, code: "low_stock", title: "Low stock", group: "stock" };
const gst: Report = {
  ...byProduct,
  code: "gst_summary",
  title: "GST summary (GSTR-1)",
  group: "gst",
  background_only: true,
  pdf: true,
};

const page = (overrides: Partial<ReportPage> = {}): ReportPage => ({
  columns: byProduct.columns,
  rows: [
    { code: "PG-1", name: "Parle-G", qty: "12.000", total: "1250.00", product_id: "p1" },
    { code: "BB-2", name: "Bourbon", qty: "3.000", total: "300.00", product_id: "p2" },
  ],
  totals: { qty: "15.000", total: "1550.00" },
  count: 2,
  page: 1,
  page_size: 50,
  own_shops: false,
  notes: ["Returns are taken off in the period of their credit note."],
  ...overrides,
});

beforeEach(() => {
  window.localStorage.clear();
  toast.error.mockReset();
  toast.success.mockReset();
  router.push.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ReportsHub", () => {
  it("lists the reports the server offers, by group, in the app's words", async () => {
    mockApi({ "/api/v1/reports/": () => [200, [byProduct, lowStock, gst]] });
    renderWithIntl(<ReportsHub />);
    const sales = await screen.findByRole("region", { name: "Sales" });
    const link = within(sales).getByRole("link", { name: /Sales by product/ });
    expect(link).toHaveAttribute("href", "/manage/reports/sales_by_product");
    // The app's own words, not the server's.
    expect(within(sales).getByText(/What sold, net of returns/)).toBeInTheDocument();
    expect(screen.queryByText("Server description")).not.toBeInTheDocument();
    // Low stock keeps its own, richer screen.
    expect(screen.getByRole("link", { name: /Low stock/ })).toHaveAttribute(
      "href",
      "/manage/reports/low-stock",
    );
    expect(screen.getByRole("region", { name: "GST" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Money" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /My exports/ })).toHaveAttribute(
      "href",
      "/manage/reports/exports",
    );
  });

  it("says so when the role has no reports", async () => {
    mockApi({ "/api/v1/reports/": () => [200, []] });
    renderWithIntl(<ReportsHub />);
    expect(await screen.findByText("No reports for your role")).toBeInTheDocument();
  });
});

describe("ReportViewer", () => {
  it("shows the rows, whole-report totals and notes, each row linked", async () => {
    const calls = mockApi({
      "/api/v1/reports/": () => [200, [byProduct]],
      "/api/v1/reports/sales_by_product/": () => [200, page()],
    });
    renderWithIntl(<ReportViewer code="sales_by_product" />);
    expect(await screen.findByRole("heading", { name: "Sales by product" })).toBeInTheDocument();
    const link = await screen.findByRole("link", { name: "Parle-G" });
    expect(link).toHaveAttribute("href", "/manage/products/p1");
    const totals = screen.getByRole("region", { name: "Totals" });
    expect(within(totals).getByText("₹1,550.00")).toBeInTheDocument();
    expect(screen.getByText(/taken off in the period/)).toBeInTheDocument();
    const run = calls.find((c) => c.path === "/api/v1/reports/sales_by_product/")!;
    expect(run.url.searchParams.get("date_from")).toBe("2026-09-01");
    expect(run.url.searchParams.get("group_by")).toBeNull();
  });

  it("sends a changed filter from page one and remembers it, but not the dates", async () => {
    const calls = mockApi({
      "/api/v1/reports/": () => [200, [byProduct]],
      "/api/v1/reports/sales_by_product/": () => [200, page({ count: 120, page: 1 })],
    });
    renderWithIntl(<ReportViewer code="sales_by_product" />);
    await screen.findByRole("link", { name: "Parle-G" });
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() =>
      expect(calls.some((c) => c.url.searchParams.get("page") === "2")).toBe(true),
    );
    await userEvent.click(screen.getByRole("combobox", { name: "By" }));
    await userEvent.click(await screen.findByRole("option", { name: "Month" }));
    await waitFor(() => {
      const last = calls.filter((c) => c.path === "/api/v1/reports/sales_by_product/").at(-1)!;
      expect(last.url.searchParams.get("group_by")).toBe("month");
      expect(last.url.searchParams.get("page")).toBe("1");
    });
    const kept = JSON.parse(window.localStorage.getItem("report-filters:sales_by_product")!);
    expect(kept.values.group_by).toBe("month");
    expect(kept.values.date_from).toBeUndefined(); // dates aren't remembered
  });

  it("opens with the filters remembered in this browser", async () => {
    window.localStorage.setItem(
      "report-filters:sales_by_product",
      JSON.stringify({ values: { group_by: "week", date_from: "2026-01-01" }, labels: {} }),
    );
    const calls = mockApi({
      "/api/v1/reports/": () => [200, [byProduct]],
      "/api/v1/reports/sales_by_product/": () => [200, page()],
    });
    renderWithIntl(<ReportViewer code="sales_by_product" />);
    await screen.findByRole("link", { name: "Parle-G" });
    const run = calls.find((c) => c.path === "/api/v1/reports/sales_by_product/")!;
    expect(run.url.searchParams.get("group_by")).toBe("week");
    expect(run.url.searchParams.get("date_from")).toBe("2026-09-01");
  });

  it("shows the server's reason for a period it refuses, next to the filters", async () => {
    mockApi({
      "/api/v1/reports/": () => [200, [byProduct]],
      "/api/v1/reports/sales_by_product/": () => [
        400,
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "Some fields need attention.",
            details: { fields: { date_to: ["Choose at most 366 days."] } },
          },
        },
      ],
    });
    renderWithIntl(<ReportViewer code="sales_by_product" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("To: Choose at most 366 days.");
  });

  it("queues a large export and points to My exports", async () => {
    const calls = mockApi({
      "/api/v1/reports/": () => [200, [byProduct]],
      "/api/v1/reports/sales_by_product/": () => [200, page()],
      "POST /api/v1/reports/sales_by_product/export/": () => [
        202,
        { id: "run-1", status: "QUEUED" },
      ],
    });
    renderWithIntl(<ReportViewer code="sales_by_product" />);
    await screen.findByRole("link", { name: "Parle-G" });
    await userEvent.click(screen.getByRole("button", { name: "Export to Excel" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    const sent = calls.find((c) => c.method === "POST")!;
    expect(sent.body).toEqual({
      format: "XLSX",
      filters: { date_from: "2026-09-01", date_to: "2026-09-30" },
    });
    expect(screen.queryByRole("button", { name: "Export to PDF" })).not.toBeInTheDocument();
  });

  it("draws net sales per period on the sales summary", async () => {
    const summary: Report = { ...byProduct, code: "sales_summary", title: "Sales summary" };
    mockApi({
      "/api/v1/reports/": () => [200, [summary]],
      "/api/v1/reports/sales_summary/": () => [
        200,
        page({
          rows: [
            { period: "01-09-2026", total: "250.00" },
            { period: "02-09-2026", total: "30.00" },
          ],
        }),
      ],
    });
    renderWithIntl(<ReportViewer code="sales_summary" />);
    expect(await screen.findByText("Net sales per period on this page")).toBeInTheDocument();
  });

  it("says when a report isn't available to this person", async () => {
    mockApi({ "/api/v1/reports/": () => [200, [lowStock]] });
    renderWithIntl(<ReportViewer code="sales_by_product" />);
    expect(await screen.findByText("This report isn't available")).toBeInTheDocument();
  });

  it("tells that the GST summary is prepared in the background", async () => {
    mockApi({
      "/api/v1/reports/": () => [200, [gst]],
      "/api/v1/reports/gst_summary/": () => [200, page({ rows: [], totals: null, count: 0 })],
    });
    renderWithIntl(<ReportViewer code="gst_summary" />);
    expect(await screen.findByText(/prepared in the background/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export to PDF" })).toBeInTheDocument();
    expect(await screen.findByText("Nothing to show")).toBeInTheDocument();
  });
});

describe("MyExports", () => {
  const run = (overrides: Partial<ReportRun> = {}): ReportRun => ({
    id: "r1",
    report_code: "sales_by_invoice",
    title: "Sales by invoice",
    format: "XLSX",
    status: "READY",
    params: {},
    row_count: 39120,
    file_name: "sales-by-invoice.xlsx",
    error: "",
    created_at: "2026-10-01T05:00:00Z",
    finished_at: "2026-10-01T05:00:06Z",
    expires_at: "2026-10-08T05:00:06Z",
    download_url: "https://files.example/old",
    ...overrides,
  });

  it("lists exports and downloads with a fresh link", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    mockApi({
      "/api/v1/report-runs/": () => [
        200,
        { results: [run(), run({ id: "r2", status: "FAILED", download_url: null })] },
      ],
      "/api/v1/report-runs/r1/": () => [200, run({ download_url: "https://files.example/fresh" })],
    });
    renderWithIntl(<MyExports />);
    expect(await screen.findAllByText("Sales by invoice")).toHaveLength(2);
    expect(screen.getByText("Couldn't be made. Try exporting again.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Download sales-by-invoice.xlsx" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://files.example/fresh"));
  });

  it("has an empty state", async () => {
    mockApi({ "/api/v1/report-runs/": () => [200, { results: [] }] });
    renderWithIntl(<MyExports />);
    expect(await screen.findByText("No exports yet")).toBeInTheDocument();
  });
});
