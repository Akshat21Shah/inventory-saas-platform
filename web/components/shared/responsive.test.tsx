import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/button";
import { renderWithIntl } from "@/tests/render";
import { setViewport } from "@/tests/viewport";

import { DataTable, type DataTableColumn } from "./data-table";
import { FilterBar } from "./filter-bar";

interface Row {
  id: string;
  name: string;
  price: string;
  status: string;
  code: string;
}

const rows: Row[] = [
  { id: "1", name: "Parle-G", price: "₹10", status: "Active", code: "PG-100" },
  { id: "2", name: "Maggi", price: "₹12", status: "Inactive", code: "MG-70" },
];
const columns: DataTableColumn<Row>[] = [
  { id: "name", header: "Product", cell: ({ row }) => row.original.name },
  { id: "price", header: "Price", cell: ({ row }) => row.original.price },
  { id: "status", header: "Status", cell: ({ row }) => row.original.status },
  { id: "code", header: "Code", cell: ({ row }) => row.original.code },
  {
    id: "actions",
    header: "",
    cell: ({ row }) => <Button aria-label={`Edit ${row.original.name}`}>Edit</Button>,
  },
];

function List({ onBulk }: { onBulk: (ids: string[]) => void }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  return (
    <DataTable
      columns={columns}
      data={rows}
      getRowId={(r) => r.id}
      caption="Products"
      cardLayout={{ name: "title", price: "primary", status: "primary", code: "secondary" }}
      selection={{
        selected,
        onChange: setSelected,
        pageLabel: "Select all",
        rowLabel: (r) => `Select ${r.name}`,
        regionLabel: "Bulk actions",
        actions: <Button onClick={() => onBulk([...selected])}>Hide</Button>,
      }}
    />
  );
}

describe("DataTable on phones", () => {
  it("shows one card per row with primary fields, secondary ones behind More", async () => {
    setViewport(360);
    renderWithIntl(<List onBulk={vi.fn()} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const card = screen.getByText("Parle-G").closest("li")!;
    expect(within(card).getByText("Price")).toBeVisible();
    expect(within(card).getByText("₹10")).toBeVisible();
    expect(within(card).queryByText("PG-100")).not.toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Edit Parle-G" })).toBeVisible();
    await userEvent.click(within(card).getByRole("button", { name: "More" }));
    expect(within(card).getByText("PG-100")).toBeVisible();
  });

  it("selects rows in a Select mode and acts on them from a bottom bar", async () => {
    setViewport(360);
    const onBulk = vi.fn();
    renderWithIntl(<List onBulk={onBulk} />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Select" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Select Maggi" }));
    const bar = screen.getByRole("region", { name: "Bulk actions" });
    expect(bar).toHaveClass("fixed");
    expect(within(bar).getByText("1 selected")).toBeVisible();
    await userEvent.click(within(bar).getByRole("button", { name: "Hide" }));
    expect(onBulk).toHaveBeenCalledWith(["2"]);
  });

  it("stays a table with a checkbox column on laptops", () => {
    setViewport(1440);
    renderWithIntl(<List onBulk={vi.fn()} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select all" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Select" })).not.toBeInTheDocument();
  });
});

describe("FilterBar", () => {
  const bar = (
    <FilterBar
      active={2}
      onClear={vi.fn()}
      search={<input aria-label="Search" />}
      filters={<select aria-label="Brand" />}
    />
  );

  it("keeps search visible and moves filters into a sheet on phones", async () => {
    setViewport(360);
    renderWithIntl(bar);
    expect(screen.getByRole("textbox", { name: "Search" })).toBeVisible();
    expect(screen.queryByRole("combobox", { name: "Brand" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Filters (2)" }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByRole("combobox", { name: "Brand" })).toBeVisible();
    await userEvent.click(within(sheet).getByRole("button", { name: "Show results" }));
  });

  it("shows everything inline on wider screens", () => {
    setViewport(1024);
    renderWithIntl(bar);
    expect(screen.getByRole("combobox", { name: "Brand" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Filters/ })).not.toBeInTheDocument();
  });
});
