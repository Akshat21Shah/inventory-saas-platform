import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SupplierDetail, SupplierList } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { ProductSuppliersPanel } from "./product-suppliers";
import { ReceiptSuppliersPage } from "./receipt-suppliers";
import { NewSupplierPage, SupplierPage, SuppliersPage } from "./suppliers";

let permissions = new Set<string>();
const auth = {
  me: { id: "u1" },
  can: (p: string) => permissions.has(p),
  feature: (code: string) => code === "purchasing",
};
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const router = { replace: vi.fn(), push: vi.fn() };
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/manage",
  useSearchParams: () => new URLSearchParams(),
}));

beforeEach(() => {
  permissions = new Set(["purchasing.view", "purchasing.manage", "costs.view"]);
  router.replace.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

const supplier = (id: string, name: string, extra: Partial<SupplierList> = {}): SupplierList => ({
  id,
  code: `S-000${id}`,
  name,
  gstin: null,
  state_code: "27",
  contact_name: "Ravi Mehta",
  phone: "9822012345",
  email: "orders@example.com",
  city: "Pune",
  lead_time_days: 5,
  is_active: true,
  product_count: 12,
  ...extra,
});

const detail = (extra: Partial<SupplierDetail> = {}): SupplierDetail => ({
  ...supplier("1", "Hindustan Traders"),
  state_name: "Maharashtra",
  address_line1: "Plot 4, MIDC",
  address_line2: "",
  pincode: "411019",
  payment_terms_days: 30,
  notes: "",
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T10:00:00Z",
  ...extra,
});

const page = (results: unknown[]) =>
  [200, { next: null, previous: null, results }] as [number, unknown];
const states = {
  "/api/v1/public/states/": () => [200, [{ code: "27", name: "Maharashtra" }]] as [number, unknown],
};

describe("SuppliersPage", () => {
  it("lists suppliers with their contact and delivery days, and searches", async () => {
    const calls = mockApi({
      "/api/v1/suppliers/": () =>
        page([
          supplier("1", "Hindustan Traders"),
          supplier("2", "Patel Agencies", { lead_time_days: null, is_active: false }),
        ]),
    });
    renderWithIntl(<SuppliersPage />);
    const row = (await screen.findByText("Hindustan Traders")).closest("tr")!;
    expect(within(row).getByText("Ravi Mehta · 9822012345")).toBeInTheDocument();
    expect(within(row).getByText("5 days")).toBeInTheDocument();
    const patel = screen.getByText("Patel Agencies").closest("tr")!;
    expect(within(patel).getByText("Your usual time")).toBeInTheDocument();
    expect(within(patel).getByText("Inactive")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("searchbox", { name: "Search suppliers" }), "hind");
    await waitFor(() => expect(calls.at(-1)?.url.searchParams.get("search")).toBe("hind"));
    expect(screen.getByRole("link", { name: /From past receipts/ })).toBeInTheDocument();
  });

  it("offers adding and importing only to those who manage purchasing", async () => {
    permissions.delete("purchasing.manage");
    mockApi({ "/api/v1/suppliers/": () => page([]) });
    renderWithIntl(<SuppliersPage />);
    expect(await screen.findByText("No suppliers yet")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Add supplier/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /Import/ })).toBeNull();
  });
});

describe("supplier editor", () => {
  it("adds a supplier and shows the server's words for a field", async () => {
    let attempt = 0;
    const calls = mockApi({
      ...states,
      "POST /api/v1/suppliers/": () => {
        attempt += 1;
        return attempt === 1
          ? [
              400,
              {
                error: {
                  code: "VALIDATION_ERROR",
                  message: "",
                  details: { fields: { gstin: ["Another supplier has this GSTIN."] } },
                },
              },
            ]
          : [201, detail({ id: "new1" })];
      },
    });
    renderWithIntl(<NewSupplierPage />);
    await userEvent.type(screen.getByRole("textbox", { name: /^Name/ }), "Hindustan Traders");
    await userEvent.type(screen.getByRole("textbox", { name: /GSTIN/ }), "27aagfk7315r1zp");
    await userEvent.type(screen.getByRole("textbox", { name: /Delivery days/ }), "5");
    await userEvent.click(screen.getByRole("button", { name: "Add supplier" }));
    expect(await screen.findByText("Another supplier has this GSTIN.")).toBeInTheDocument();
    const body = calls.find((c) => c.method === "POST")!.body as Record<string, unknown>;
    expect(body).toMatchObject({
      name: "Hindustan Traders",
      gstin: "27AAGFK7315R1ZP",
      lead_time_days: 5,
      state_code: null,
    });
    await userEvent.click(screen.getByRole("button", { name: "Add supplier" }));
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/manage/purchasing/suppliers/new1"),
    );
  });

  it("shows a supplier with what it supplies, and why it can't be deleted", async () => {
    mockApi({
      ...states,
      "/api/v1/suppliers/1/": () => [200, detail()],
      "/api/v1/suppliers/1/products/": () =>
        page([
          {
            id: "l1",
            supplier_id: "1",
            supplier_code_number: "S-0001",
            supplier_name: "Hindustan Traders",
            product_id: "p1",
            product_code: "TEA",
            product_name: "Tata Tea Gold",
            is_preferred: true,
            supplier_code: "HT-77",
            lead_time_days: null,
            pack_size: "12.000",
            last_unit_cost: "41.5000",
          },
        ]),
      "DELETE /api/v1/suppliers/1/": () => [
        400,
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "",
            details: {
              fields: {
                supplier: ["This supplier has open purchase orders. Cancel or close them first."],
              },
            },
          },
        },
      ],
    });
    renderWithIntl(<SupplierPage supplierId="1" />);
    expect(await screen.findByRole("heading", { name: "Hindustan Traders" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /^Name/ })).toHaveValue("Hindustan Traders");
    const tea = (await screen.findByText("Tata Tea Gold")).closest("tr")!;
    expect(within(tea).getByText("₹41.50")).toBeInTheDocument();
    expect(within(tea).getByText("Preferred")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "This supplier has open purchase orders. Cancel or close them first.",
      ),
    );
  });
});

describe("ReceiptSuppliersPage", () => {
  it("links same-name receipts and makes new suppliers for the rest, once confirmed", async () => {
    const calls = mockApi({
      "/api/v1/suppliers/": () => page([supplier("1", "PATEL agencies")]),
      "/api/v1/suppliers/from-receipts/": () => [
        200,
        [
          {
            name: "Hindustan Traders",
            receipts: 2,
            last_date: "2026-09-20",
            match_id: null,
            match_name: "",
          },
          {
            name: "Patel Agencies",
            receipts: 3,
            last_date: "2026-09-10",
            match_id: "1",
            match_name: "PATEL agencies",
          },
          { name: "Gupta Bros", receipts: 1, last_date: null, match_id: null, match_name: "" },
        ],
      ],
      "POST /api/v1/suppliers/from-receipts/": () => [
        200,
        { suppliers_created: 1, receipts_linked: 5 },
      ],
    });
    renderWithIntl(<ReceiptSuppliersPage />);
    expect(
      await screen.findByText("Same name as your supplier PATEL agencies"),
    ).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "What is Patel Agencies?" })).toHaveTextContent(
      "It is PATEL agencies",
    );
    expect(screen.getByRole("combobox", { name: "What is Gupta Bros?" })).toHaveTextContent(
      "Decide later",
    );
    await userEvent.click(screen.getByRole("combobox", { name: "What is Hindustan Traders?" }));
    await userEvent.click(await screen.findByRole("option", { name: "Make it a new supplier" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm 2 names" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({
      choices: [
        { name: "Hindustan Traders", new: true },
        { name: "Patel Agencies", supplier_id: "1" },
      ],
    });
  });
});

describe("ProductSuppliersPanel", () => {
  it("shows who a product is bought from and saves a new preferred supplier", async () => {
    const calls = mockApi({
      "/api/v1/products/p1/suppliers/": () => [
        200,
        [
          {
            id: "l1",
            supplier_id: "1",
            supplier_code_number: "S-0001",
            supplier_name: "Hindustan Traders",
            product_id: "p1",
            product_code: "TEA",
            product_name: "Tata Tea Gold",
            is_preferred: true,
            supplier_code: "HT-77",
            lead_time_days: 4,
            pack_size: "12.000",
            last_unit_cost: "41.5000",
          },
        ],
      ],
      "PUT /api/v1/products/p1/suppliers/": () => [200, []],
      "/api/v1/suppliers/": () =>
        page([supplier("1", "Hindustan Traders"), supplier("2", "Patel Agencies")]),
    });
    renderWithIntl(<ProductSuppliersPanel productId="p1" />);
    expect(await screen.findByText("their code HT-77 · 4 days · pack of")).toBeInTheDocument();
    expect(screen.getByText("₹41.50")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    await userEvent.click(screen.getByRole("button", { name: "Add a supplier" }));
    const pickers = screen.getAllByRole("combobox", { name: "Supplier" });
    await userEvent.click(pickers[1]!);
    await userEvent.click(await screen.findByRole("option", { name: "Patel Agencies" }));
    await userEvent.click(screen.getAllByRole("radio", { name: "Preferred" })[1]!);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({
      links: [
        {
          supplier_id: "1",
          is_preferred: false,
          supplier_code: "HT-77",
          lead_time_days: 4,
          pack_size: "12",
        },
        {
          supplier_id: "2",
          is_preferred: true,
          supplier_code: "",
          lead_time_days: null,
          pack_size: null,
        },
      ],
    });
  });
});
