import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImportJob } from "@/lib/api/generated/model";
import { mockApi } from "@/tests/mock-api";
import { renderWithIntl } from "@/tests/render";

import { ImportJobPage, ImportStartPage } from "./import-wizard";

const auth = { me: { id: "u1" }, can: () => true };
vi.mock("@/components/auth/auth-provider", () => ({ useAuth: () => auth }));
const router = { replace: vi.fn(), push: vi.fn() };
let search = new URLSearchParams("kind=PRODUCTS");
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => search,
  usePathname: () => "/manage/imports/new",
}));

afterEach(() => {
  vi.unstubAllGlobals();
  search = new URLSearchParams("kind=PRODUCTS");
});

const job = (extra: Partial<ImportJob>): ImportJob => ({
  id: "job-1",
  kind: "PRODUCTS",
  mode: "ADD_OR_UPDATE",
  status: "VALIDATED",
  file_name: "prices.xlsx",
  problem: "",
  counts: { total: 4, new: 1, update: 1, unchanged: 1, error: 1, changes: 2 },
  notes: ["Column “Remarks” isn't used and was skipped."],
  errors: [{ row: 5, key: "A-5", messages: ["Row 5, column “Price”: ten isn't a number."] }],
  changes: [
    {
      row: 2,
      key: "PG-100",
      action: "UPDATE",
      changes: { Price: ["9.00", "9.50"], "Product name": ["Parle-G", "Parle-G Gold"] },
      highlight: ["Price"],
      warnings: [],
    },
    { row: 3, key: "NEW-1", action: "NEW", changes: {}, highlight: [], warnings: [] },
  ],
  created_by: "Asha",
  created_at: "2026-09-25T10:00:00Z",
  validated_at: "2026-09-25T10:00:05Z",
  committed_at: null,
  ...extra,
});

describe("ImportStartPage", () => {
  it("has no mode chosen until the distributor picks one", async () => {
    const calls = mockApi({ "POST /api/v1/imports/": () => [201, job({ status: "VALIDATING" })] });
    renderWithIntl(<ImportStartPage />);
    expect(screen.getByRole("radio", { name: /^Products/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /^Add new only/ })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /^Add new and update existing/ })).not.toBeChecked();

    const file = new File(["x"], "products.xlsx");
    await userEvent.upload(screen.getByLabelText("Choose an Excel or CSV file"), file);
    const check = screen.getByRole("button", { name: "Check the file" });
    expect(check).toBeDisabled();
    expect(screen.getByText("Choose what should happen to existing rows first.")).toBeVisible();

    await userEvent.click(screen.getByRole("radio", { name: /^Add new and update existing/ }));
    await userEvent.click(check);
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/manage/imports/job-1"));
    const body = calls.find((c) => c.method === "POST")?.body as FormData;
    expect([body.get("kind"), body.get("mode")]).toEqual(["PRODUCTS", "ADD_OR_UPDATE"]);
  });
});

describe("ImportJobPage", () => {
  it("previews old and new values, highlights price changes, and imports on confirm", async () => {
    let current = job({});
    const calls = mockApi({
      "/api/v1/imports/job-1/": () => [200, current],
      "POST /api/v1/imports/job-1/commit/": () => {
        current = job({
          status: "COMMITTED",
          counts: { ...job({}).counts!, applied: 2, failed: 0 },
        });
        return [202, current];
      },
    });
    renderWithIntl(<ImportJobPage jobId="job-1" />);
    const price = (await screen.findByText("Price:")).closest("li")!;
    expect(price).toHaveAttribute("data-highlight", "true");
    expect(within(price).getByText("9.00")).toBeInTheDocument();
    expect(within(price).getByText("9.50")).toBeInTheDocument();
    expect(within(price).getByText("Price change")).toBeInTheDocument();
    const name = screen.getByText("Product name:").closest("li")!;
    expect(name).not.toHaveAttribute("data-highlight");
    expect(screen.getByText("Row 5, column “Price”: ten isn't a number.")).toBeInTheDocument();
    expect(
      screen.getByText(/2 rows will be saved\. 1 row with errors will be skipped\./),
    ).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Import 2 rows" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Import 2 rows" }),
    );
    expect(await screen.findByText("2 rows imported.")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/v1/imports/job-1/commit/")).toBe(true);
  });

  it("explains a file that can't be imported", async () => {
    mockApi({
      "/api/v1/imports/job-1/": () => [
        200,
        job({ status: "FAILED", problem: "The file is missing these columns: Unit." }),
      ],
    });
    renderWithIntl(<ImportJobPage jobId="job-1" />);
    expect(await screen.findByText("The file is missing these columns: Unit.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Try another file" })).toHaveAttribute(
      "href",
      "/manage/imports/new?kind=PRODUCTS",
    );
  });
});
