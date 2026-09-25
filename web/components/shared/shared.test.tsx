import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/tests/render";

import { ConfirmDialog } from "./confirm-dialog";
import { DataTable, type DataTableColumn } from "./data-table";
import { ErrorState } from "./error-state";
import { FormField } from "./form-field";
import { MoneyText } from "./money-text";
import { StatusBadge } from "./status-badge";

describe("MoneyText", () => {
  it("renders INR with tabular numbers", () => {
    renderWithIntl(<MoneyText value="123456.5" />);
    expect(screen.getByText("₹1,23,456.50")).toHaveClass("tabular-nums");
  });
});

describe("StatusBadge", () => {
  it("always pairs the colour tone with a translated label", () => {
    renderWithIntl(<StatusBadge status="ON_HOLD" />);
    const badge = screen.getByText("On hold");
    expect(badge).toHaveAttribute("data-tone", "warning");
  });

  it("falls back to the raw code for unknown statuses", () => {
    renderWithIntl(<StatusBadge status="SOMETHING_NEW" />);
    expect(screen.getByText("SOMETHING_NEW")).toHaveAttribute("data-tone", "neutral");
  });
});

describe("ErrorState", () => {
  it("shows a friendly translated message, never the raw error, and retries", async () => {
    const onRetry = vi.fn();
    const error = new ApiError(403, {
      code: "PERMISSION_DENIED",
      message: "stack trace here",
      details: {},
    });
    renderWithIntl(<ErrorState error={error} onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("You don't have permission to do this.");
    expect(screen.queryByText(/stack trace/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});

type Row = { id: string; name: string; price: string };
const columns: DataTableColumn<Row>[] = [
  { id: "name", header: "Name", accessorKey: "name" },
  { id: "price", header: "Price", cell: ({ row }) => <MoneyText value={row.original.price} /> },
];
const rows: Row[] = [{ id: "r1", name: "Rice", price: "10.00" }];
const none: Row[] = [];

describe("DataTable", () => {
  it("renders rows with numeric columns right-aligned", () => {
    renderWithIntl(
      <DataTable columns={columns} data={rows} getRowId={(r) => r.id} numericColumns={["price"]} />,
    );
    const table = screen.getByRole("table");
    expect(within(table).getByText("Rice")).toBeInTheDocument();
    expect(within(table).getByText("₹10.00").closest("td")).toHaveClass("text-right");
  });

  it("renders loading, empty and error states", () => {
    const { rerender } = renderWithIntl(
      <DataTable columns={columns} data={none} getRowId={(r) => r.id} isLoading />,
    );
    expect(document.querySelector("[aria-busy='true']")).toBeInTheDocument();

    rerender(
      <DataTable
        columns={columns}
        data={none}
        getRowId={(r) => r.id}
        empty={{ title: "No products" }}
      />,
    );
    expect(screen.getByText("No products")).toBeInTheDocument();

    rerender(
      <DataTable columns={columns} data={none} getRowId={(r) => r.id} error={new TypeError("x")} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("You seem to be offline.");
  });
});

describe("FormField", () => {
  it("labels the input and announces errors", () => {
    renderWithIntl(
      <FormField label="Shop name" error="Please enter the shop name" required>
        <Input />
      </FormField>,
    );
    const input = screen.getByLabelText(/Shop name/);
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Please enter the shop name");
  });
});

describe("ConfirmDialog", () => {
  it("only runs the action after confirmation", async () => {
    const onConfirm = vi.fn();
    renderWithIntl(
      <ConfirmDialog
        trigger={<button>Delete</button>}
        title="Delete this item?"
        confirmLabel="Yes, delete"
        onConfirm={onConfirm}
        destructive
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("button", { name: "Yes, delete" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
