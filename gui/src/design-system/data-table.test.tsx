import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ColumnDef } from "@tanstack/react-table";
import { describe, expect, it, vi } from "vitest";
import { DataTable } from "./data-table";

interface Person {
  id: string;
  name: string;
}

const people: Person[] = [
  { id: "1", name: "Alice" },
  { id: "2", name: "Bob" },
];

const columns: ColumnDef<Person, unknown>[] = [
  { accessorKey: "name", header: "Name" },
  {
    id: "actions",
    header: "Actions",
    enableSorting: false,
    cell: ({ row }) => <button type="button">Open {row.original.name}</button>,
  },
];

describe("DataTable", () => {
  it("renders semantic populated table markup, searches, and reports no matching results", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <DataTable
        trackingId="test.table.people"
        title="People"
        columns={columns}
        data={people}
      />
    );

    expect(container.querySelector('[data-i7n-component="data-table"][data-i7n-name="test.table.people"]')).toBeInTheDocument();
    expect(container.querySelector('[data-i7n-component="shadcn-table"][data-i7n-name="test.table.people.table"]')).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(container.querySelector("thead")).toBeInTheDocument();
    expect(container.querySelector("tbody")).toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("2 items")).toBeInTheDocument();

    const search = screen.getByRole("searchbox", { name: "Search People" });
    await user.type(search, "Bob");
    expect(screen.queryByText("Alice")).not.toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("1 item")).toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "Nobody");
    expect(screen.getByText("No matching results. Try another search.")).toBeInTheDocument();
    expect(screen.getByText("0 items")).toBeInTheDocument();
  });

  it("supports a supplied no-results message", async () => {
    const user = userEvent.setup();
    render(
      <DataTable
        trackingId="test.table.no-results"
        columns={columns}
        data={people}
        noResultsMessage="No people found"
      />
    );

    await user.type(screen.getByRole("searchbox"), "Nobody");
    expect(screen.getByRole("cell", { name: "No people found" })).toBeInTheDocument();
  });

  it("renders loading and supplied empty states inside the table", () => {
    const { rerender } = render(
      <DataTable
        trackingId="test.table.loading"
        columns={columns}
        data={[]}
        isLoading
        loadingMessage="Loading people..."
      />
    );

    expect(screen.getByLabelText("Data table")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("cell", { name: "Loading people..." })).toHaveAttribute("colspan", "2");

    rerender(
      <DataTable
        trackingId="test.table.empty"
        columns={columns}
        data={[]}
        emptyMessage="No people configured"
      />
    );
    expect(screen.getByRole("cell", { name: "No people configured" })).toBeInTheDocument();
  });

  it("supports disabling search and pagination", () => {
    render(
      <DataTable
        trackingId="test.table.unpaginated"
        columns={columns}
        data={people}
        pageSize={1}
        enableSearch={false}
        enablePagination={false}
      />
    );

    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Next page")).not.toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
  });

  it("keeps clickable rows out of the tab order and suppresses nested controls", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    render(
      <DataTable
        trackingId="test.table.activation"
        columns={columns}
        data={people}
        onRowClick={onRowClick}
      />
    );

    const aliceRow = screen.getByRole("row", { name: /Alice Open Alice/ });
    expect(aliceRow).not.toHaveAttribute("tabindex");

    await user.click(within(aliceRow).getByText("Alice"));
    expect(onRowClick).toHaveBeenLastCalledWith(people[0]);

    const nestedButton = within(aliceRow).getByRole("button", { name: "Open Alice" });
    await user.click(nestedButton);
    expect(onRowClick).toHaveBeenCalledTimes(1);
  });

  it("uses the supplied stable row identity instead of positional indexes", () => {
    render(
      <DataTable
        trackingId="test.table.stable-ids"
        columns={columns}
        data={[people[1], people[0]]}
        getRowId={(person) => person.id}
      />
    );

    expect(screen.getByRole("row", { name: /Alice Open Alice/ })).toHaveAttribute("data-row-id", "1");
    expect(screen.getByRole("row", { name: /Bob Open Bob/ })).toHaveAttribute("data-row-id", "2");
  });
});
