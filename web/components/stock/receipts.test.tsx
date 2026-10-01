import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReceiptDetail, ReceiptLine, StockRow } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";
import { setViewport } from "@/tests/viewport";

import { ReceiptEditor } from "./receipt-editor";
import { ReceiptPage, ReceiptsPage } from "./receipts";

const permissions = new Set(["stock.view", "stock.inward", "costs.view", "costs.manage"]);
const features = new Set<string>();
const auth = {
  me: { id: "u1" },
  can: (p: string) => permissions.has(p),
  feature: (code: string) => features.has(code),
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const router = { replace: vi.fn(), push: vi.fn() };
const params = { value: new URLSearchParams() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/manage/stock/inwards",
  useSearchParams: () => params.value,
}));

afterEach(() => {
  vi.unstubAllGlobals();
  setViewport(1440);
  router.replace.mockReset();
  params.value = new URLSearchParams();
  for (const p of ["costs.view", "costs.manage", "products.manage"]) permissions.add(p);
  permissions.delete("products.manage");
});

const PCS = { code: "PCS", allows_decimal: false };
const BOX = { code: "BOX", allows_decimal: false };
const product = (id: string, name: string, extra: Partial<StockRow> = {}): StockRow => ({
  id,
  code: id.toUpperCase(),
  name,
  unit: PCS,
  pack_unit: null,
  pack_size: null,
  category: "",
  brand: "",
  is_active: true,
  reorder_level: "0.000",
  on_hand: "10.000",
  reserved: "0.000",
  available: "10.000",
  backordered: "0.000",
  status: "IN_STOCK",
  thumbnail_url: null,
  ...extra,
});
const parle = product("p1", "Parle-G 100g");
const marie = product("p2", "Marie Gold", { pack_unit: BOX, pack_size: "12.000" });
const page = (results: unknown[]) => ({ next: null, previous: null, results });
const detail = (extra: Partial<ReceiptDetail> = {}): ReceiptDetail => ({
  id: "r1",
  number: "GRN-2026-00007",
  status: "POSTED",
  supplier_name: "Acme",
  supplier_id: null,
  purchase_order_id: null,
  purchase_order_number: null,
  supplier_ref: "",
  bill_number: "B-1",
  bill_date: null,
  notes: "",
  line_count: 1,
  total_cost: null,
  cost_pending_lines: 0,
  posted_at: "2026-09-26T08:00:00Z",
  posted_by: "Warehouse",
  created_at: "2026-09-26T08:00:00Z",
  created_by: "Warehouse",
  lines: [],
  ...extra,
});
const line = (extra: Partial<ReceiptLine> = {}): ReceiptLine => ({
  id: "l1",
  line_no: 1,
  product: {
    id: "p2",
    code: "P2",
    name: "Marie Gold",
    unit: PCS,
    pack_unit: BOX,
    pack_size: "12.000",
  },
  entered_unit: "PACK",
  entered_qty: "2.000",
  quantity: "24.000",
  entered_cost: null,
  unit_cost: null,
  line_cost: null,
  cost_status: "PENDING",
  purchase_order_line_id: null,
  ordered: null,
  received_before: null,
  ...extra,
});
const lookup = (url: URL): [number, unknown] =>
  url.searchParams.get("code") === "8901719101038"
    ? [200, parle]
    : url.searchParams.get("code") === "MARIE"
      ? [200, marie]
      : [404, { error: { code: "NOT_FOUND", message: "", details: {} } }];

describe("receiving goods on a laptop", () => {
  it("scans, counts repeated scans, takes costs and posts with an idempotency key", async () => {
    const calls = mockApi({
      "/api/v1/stock/lookup/": (_b, url) => lookup(url),
      "/api/v1/stock/": () => [200, page([])],
      "POST /api/v1/stock/inwards/": () => [201, detail()],
    });
    renderWithIntl(<ReceiptEditor />);
    const scan = screen.getByLabelText("Scan or search a product");
    await userEvent.type(scan, "8901719101038{Enter}");
    const qty = await screen.findByLabelText("Quantity of Parle-G 100g in PCS");
    expect(qty).toHaveValue("1");
    await userEvent.type(scan, "8901719101038{Enter}");
    await waitFor(() => expect(qty).toHaveValue("2"));
    // Enter in the quantity moves to the cost, Enter there back to the scan bar.
    await userEvent.click(qty);
    await userEvent.keyboard("{Enter}");
    const cost = screen.getByLabelText("Cost per PCS (before GST): Parle-G 100g");
    expect(cost).toHaveFocus();
    await userEvent.type(cost, "7.5{Enter}");
    expect(scan).toHaveFocus();
    await userEvent.type(scan, "MARIE{Enter}");
    await userEvent.click(await screen.findByRole("radio", { name: "BOX of 12 PCS" }));
    await userEvent.type(screen.getByLabelText("Supplier"), "Acme Traders");

    await userEvent.click(screen.getByRole("button", { name: "Save and post" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Post" }),
    );
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/manage/stock/inwards/r1"));
    const post = calls.find((c) => c.method === "POST" && c.path === "/api/v1/stock/inwards/");
    expect(post?.body).toMatchObject({
      supplier_name: "Acme Traders",
      post: true,
      lines: [
        { product_id: "p1", entered_unit: "BASE", entered_qty: "2", entered_cost: "7.5" },
        { product_id: "p2", entered_unit: "PACK", entered_qty: "1", entered_cost: null },
      ],
    });
    expect(post?.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f]{32}$/);
  });

  it("shows the server's message next to the line it is about", async () => {
    mockApi({
      "/api/v1/stock/lookup/": (_b, url) => lookup(url),
      "/api/v1/stock/": () => [200, page([])],
      "POST /api/v1/stock/inwards/": () => [
        400,
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "Some fields need attention.",
            details: { fields: { "lines.1": ["PCS is counted in whole numbers."] } },
          },
        },
      ],
    });
    renderWithIntl(<ReceiptEditor />);
    await userEvent.type(screen.getByLabelText("Scan or search a product"), "8901719101038{Enter}");
    await screen.findByLabelText("Quantity of Parle-G 100g in PCS");
    await userEvent.click(screen.getByRole("button", { name: "Save as draft" }));
    expect(await screen.findByText("PCS is counted in whole numbers.")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("lets product managers link an unknown barcode to a product", async () => {
    permissions.add("products.manage");
    const calls = mockApi({
      "/api/v1/stock/lookup/": (_b, url) => lookup(url),
      "/api/v1/stock/": () => [200, page([parle])],
      "POST /api/v1/products/p1/barcodes/": () => [201, { id: "b1", barcode: "999000111" }],
    });
    renderWithIntl(<ReceiptEditor />);
    const scan = screen.getByLabelText("Scan or search a product");
    await userEvent.type(scan, "999000111{Enter}");
    expect(
      await screen.findByText("No product has the barcode or code 999000111."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Link this barcode to a product" }));
    await userEvent.type(scan, "parle");
    await userEvent.click(await screen.findByRole("button", { name: /Parle-G 100g/ }));
    await screen.findByLabelText("Quantity of Parle-G 100g in PCS");
    expect(calls.find((c) => c.path === "/api/v1/products/p1/barcodes/")?.body).toEqual({
      barcode: "999000111",
    });
  });
});

describe("receiving against a purchase order (purchasing on)", () => {
  it("shows the order and what was ordered, and asks before receiving more than ordered", async () => {
    features.add("purchasing");
    const draft = detail({
      id: "r9",
      status: "DRAFT",
      number: null,
      purchase_order_id: "po1",
      purchase_order_number: "PO-2026-00003",
      supplier_id: "s1",
      supplier_name: "Hindustan Traders",
      lines: [
        line({
          id: "l1",
          entered_unit: "BASE",
          entered_qty: "12.000",
          quantity: "12.000",
          purchase_order_line_id: "pol1",
          ordered: "10.000",
          received_before: "0.000",
        }),
      ],
    });
    let attempt = 0;
    const posted = { ...draft, status: "POSTED" as const, number: "GRN-2026-00009" };
    const calls = mockApi({
      "/api/v1/stock/": () => [200, page([])],
      "/api/v1/stock/inwards/r9/": () => [200, attempt === 2 ? posted : draft],
      "PATCH /api/v1/stock/inwards/r9/": () => [200, draft],
      "POST /api/v1/stock/inwards/r9/post/": () => {
        attempt += 1;
        return attempt === 1
          ? [
              409,
              {
                error: {
                  code: "OVER_RECEIPT",
                  message: "More is being received than was ordered.",
                  details: {
                    lines: [
                      {
                        line_id: "pol1",
                        product_code: "P2",
                        ordered: "10.000",
                        received_before: "0.000",
                        receiving: "12.000",
                        beyond_tolerance: true,
                      },
                    ],
                    tolerance_percent: 10,
                    can_confirm: true,
                  },
                },
              },
            ]
          : [200, posted];
      },
    });
    renderWithIntl(<ReceiptPage receiptId="r9" />);
    expect(await screen.findByRole("link", { name: "PO-2026-00003" })).toHaveAttribute(
      "href",
      "/manage/purchasing/orders/po1",
    );
    expect(screen.getByText("Ordered 10 PCS, 0 received before")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Supplier" })).toBeNull(); // the order's own
    await userEvent.click(screen.getByRole("button", { name: "Post" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Post" }),
    );
    const dialog = await screen.findByRole("dialog", { name: "More than ordered" });
    expect(
      within(dialog).getByText("P2: ordered 10, 0 received before, 12 now"),
    ).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Receive anyway" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/manage/stock/inwards/r9"));
    // Already on the draft's address: the page shows the receipt again, now posted.
    expect(await screen.findByRole("heading", { name: "GRN-2026-00009" })).toBeInTheDocument();
    const posts = calls.filter((c) => c.path === "/api/v1/stock/inwards/r9/post/");
    expect(posts.map((c) => c.body)).toEqual([{}, { confirm_over_receipt: true }]);
    expect(posts[0]!.headers.get("Idempotency-Key")).not.toEqual(
      posts[1]!.headers.get("Idempotency-Key"),
    );
    features.delete("purchasing");
  });

  it("picks the supplier from the list on a new receipt", async () => {
    features.add("purchasing");
    const calls = mockApi({
      "/api/v1/stock/lookup/": (_b, url) => lookup(url),
      "/api/v1/stock/": () => [200, page([])],
      "/api/v1/suppliers/": () => [200, page([{ id: "s1", name: "Hindustan Traders" }])],
      "POST /api/v1/stock/inwards/": () => [201, detail()],
    });
    renderWithIntl(<ReceiptEditor />);
    await userEvent.type(screen.getByLabelText("Scan or search a product"), "8901719101038{Enter}");
    await screen.findByLabelText("Quantity of Parle-G 100g in PCS");
    await userEvent.click(screen.getByRole("combobox", { name: "Supplier" }));
    await userEvent.click(await screen.findByRole("option", { name: "Hindustan Traders" }));
    expect(screen.queryByRole("textbox", { name: "Supplier" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save as draft" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ supplier_id: "s1" }),
    );
    features.delete("purchasing");
  });
});

describe("receiving goods on a phone", () => {
  it("uses large steppers and never sends costs for warehouse staff", async () => {
    setViewport(360);
    permissions.delete("costs.view");
    permissions.delete("costs.manage");
    const calls = mockApi({
      "/api/v1/stock/lookup/": (_b, url) => lookup(url),
      "/api/v1/stock/": () => [200, page([])],
      "POST /api/v1/stock/inwards/": () => [201, detail({ id: "r9" })],
    });
    renderWithIntl(<ReceiptEditor />);
    expect(
      screen.getByText("Costs are added later by someone who manages costs."),
    ).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Scan or search a product"), "8901719101038{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: "One more Parle-G 100g" }));
    await userEvent.click(screen.getByRole("button", { name: "One more Parle-G 100g" }));
    expect(screen.getByLabelText("Quantity of Parle-G 100g in PCS")).toHaveValue("3");
    expect(screen.queryByText(/Cost per/)).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save and post" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Post" }),
    );
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/manage/stock/inwards/r9"));
    const body = calls.find((c) => c.method === "POST")?.body as { lines: object[] };
    expect(body.lines[0]).not.toHaveProperty("entered_cost");
  });
});

describe("a posted receipt", () => {
  it("lets cost managers add the missing costs", async () => {
    const calls = mockApi({
      "/api/v1/stock/inwards/r1/": () => [200, detail({ cost_pending_lines: 1, lines: [line()] })],
      "POST /api/v1/stock/inwards/r1/complete-costs/": () => [200, detail()],
    });
    renderWithIntl(<ReceiptPage receiptId="r1" />);
    expect(await screen.findByText("GRN-2026-00007")).toBeInTheDocument();
    expect(screen.getByText("1 line waiting for cost")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Cost per BOX/), "96");
    await userEvent.click(screen.getByRole("button", { name: "Save 1 cost" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/complete-costs/"))?.body).toEqual({
        costs: [{ line_id: "l1", entered_cost: "96" }],
      }),
    );
  });

  it("has no cost form for staff who only see costs", async () => {
    permissions.delete("costs.manage");
    mockApi({
      "/api/v1/stock/inwards/r1/": () => [200, detail({ cost_pending_lines: 1, lines: [line()] })],
    });
    renderWithIntl(<ReceiptPage receiptId="r1" />);
    await screen.findByText("GRN-2026-00007");
    expect(screen.queryByText("Add the missing costs")).not.toBeInTheDocument();
  });
});

describe("the receipts list", () => {
  it("opens on receipts waiting for costs when linked from the stock page", async () => {
    params.value = new URLSearchParams("awaiting_cost=true");
    const calls = mockApi({
      "/api/v1/stock/inwards/": () => [200, page([detail({ cost_pending_lines: 2 })])],
    });
    renderWithIntl(<ReceiptsPage />);
    expect(await screen.findByRole("link", { name: /GRN-2026-00007/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Waiting for costs" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(calls[0]?.url.searchParams.get("awaiting_cost")).toBe("true");
    expect(screen.getByText("2 lines waiting for cost")).toBeInTheDocument();
  });
});
