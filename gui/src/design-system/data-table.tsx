/**
 * @source i7n-ui/src/design-system/data-table.tsx
 * @deps @tanstack/react-table, lucide-react, @/lib/utils, ./input, ./ui/table
 * @tracking-component data-table
 */
"use client";

import { useState, type MouseEvent, type ReactNode } from "react";
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type Row,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "./input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";

const INTERACTIVE_ELEMENT_SELECTOR = [
  "a",
  "button",
  "input",
  "select",
  "textarea",
  "label",
  "summary",
  "[contenteditable='true']",
  "[role='button']",
  "[role='checkbox']",
  "[role='link']",
  "[role='menuitem']",
  "[role='radio']",
  "[role='switch']",
  "[role='tab']",
].join(", ");

function isNestedInteractiveTarget(event: MouseEvent<HTMLTableRowElement>) {
  const target = event.target;
  return target instanceof Element && target !== event.currentTarget && Boolean(target.closest(INTERACTIVE_ELEMENT_SELECTOR));
}

export interface DataTableProps<TData> {
  /** Accessor values drive search and sorting; cell renderers only change presentation. */
  columns: ColumnDef<TData, unknown>[];
  data: TData[];
  title?: string;
  searchPlaceholder?: string;
  pageSize?: number;
  headerActions?: ReactNode;
  emptyMessage?: string;
  noResultsMessage?: string;
  loadingMessage?: string;
  isLoading?: boolean;
  /** Hides the global-filter input while retaining sorting and all table semantics. */
  enableSearch?: boolean;
  /** When false, renders every filtered row and omits pagination controls. */
  enablePagination?: boolean;
  /** Singular label used by the result count, for example "agent". */
  itemLabel?: string;
  className?: string;
  /** Supplies the stable domain identity used for TanStack row and cell IDs. */
  getRowId?: (originalRow: TData, index: number, parent?: Row<TData>) => string;
  /** Optional pointer convenience. The row remains non-focusable; expose the action in a real link or button cell. */
  onRowClick?: (row: TData) => void;
  /** Required analytics name. Format: `<surface>.<component>.<purpose>` (kebab-case). */
  trackingId: string;
}

export function DataTable<TData>({
  columns,
  data,
  title,
  searchPlaceholder = "Search...",
  pageSize = 10,
  headerActions,
  emptyMessage = "No items yet",
  noResultsMessage = "No matching results. Try another search.",
  loadingMessage = "Loading...",
  isLoading = false,
  enableSearch = true,
  enablePagination = true,
  itemLabel = "item",
  className,
  getRowId,
  onRowClick,
  trackingId,
}: DataTableProps<TData>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [search, setSearch] = useState("");

  const table = useReactTable({
    data,
    columns,
    getRowId,
    state: { sorting, globalFilter: search },
    onSortingChange: setSorting,
    onGlobalFilterChange: setSearch,
    globalFilterFn: "includesString",
    sortDescFirst: false,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: enableSearch ? getFilteredRowModel() : undefined,
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: enablePagination ? getPaginationRowModel() : undefined,
    initialState: { pagination: { pageSize } },
  });

  const filteredCount = table.getFilteredRowModel().rows.length;
  const pageIndex = table.getState().pagination.pageIndex;
  const visibleRows = table.getRowModel().rows;
  const start = filteredCount ? pageIndex * table.getState().pagination.pageSize + 1 : 0;
  const end = Math.min(start + visibleRows.length - 1, filteredCount);
  const itemCountLabel = `${filteredCount} ${itemLabel}${filteredCount === 1 ? "" : "s"}`;
  const columnCount = table.getVisibleLeafColumns().length;

  return (
    <section
      className={cn("ds-data-table", className)}
      aria-label={title ?? "Data table"}
      aria-busy={isLoading || undefined}
      data-i7n-component="data-table"
      data-i7n-name={trackingId}
    >
      <div className="ds-data-table-toolbar">
        <div className="ds-data-table-heading">
          {title && <h2>{title}</h2>}
          <span className="ds-data-table-count" aria-live="polite">{itemCountLabel}</span>
        </div>
        {(enableSearch || headerActions) && (
          <div className="ds-data-table-tools">
            {enableSearch && (
              <label className="ds-data-table-search">
                <Search size={16} aria-hidden="true" />
                <Input
                  trackingId={`${trackingId}.search`}
                  type="search"
                  size="sm"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={searchPlaceholder}
                  aria-label={title ? `Search ${title}` : "Search table"}
                  disabled={isLoading}
                />
              </label>
            )}
            {headerActions}
          </div>
        )}
      </div>

      <div className="ds-data-table-scroll">
        <Table trackingId={`${trackingId}.table`}>
          <TableHeader>
            {table.getHeaderGroups().map((group) => (
              <TableRow key={group.id}>
                {group.headers.map((header) => {
                  const direction = header.column.getIsSorted();
                  return (
                    <TableHead
                      key={header.id}
                      scope="col"
                      aria-sort={direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none"}
                      data-align={header.column.columnDef.meta?.align ?? "left"}
                    >
                      {header.isPlaceholder ? null : header.column.getCanSort() ? (
                        <button
                          type="button"
                          className="ds-data-table-sort"
                          data-i7n-name={`${trackingId}.sort.${header.column.id}`}
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {direction === "asc" ? <ArrowUp size={14} aria-hidden="true" /> :
                            direction === "desc" ? <ArrowDown size={14} aria-hidden="true" /> :
                              <ArrowUpDown size={14} aria-hidden="true" />}
                        </button>
                      ) : flexRender(header.column.columnDef.header, header.getContext())}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell className="ds-data-table-empty" colSpan={columnCount}>
                  {loadingMessage}
                </TableCell>
              </TableRow>
            ) : visibleRows.length ? visibleRows.map((row) => (
              <TableRow
                key={row.id}
                data-row-id={row.id}
                data-clickable={onRowClick ? "" : undefined}
                onClick={onRowClick ? (event) => {
                  if (isNestedInteractiveTarget(event)) return;
                  onRowClick(row.original);
                } : undefined}
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id} data-align={cell.column.columnDef.meta?.align ?? "left"}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            )) : (
              <TableRow><TableCell className="ds-data-table-empty" colSpan={columnCount}>
                {data.length ? noResultsMessage : emptyMessage}
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {!isLoading && enablePagination && filteredCount > pageSize && (
        <div className="ds-data-table-footer">
          <span>Showing {start}–{end} of {filteredCount}</span>
          <div className="ds-data-table-pagination">
            <button
              type="button"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
              aria-label="Previous page"
              data-i7n-name={`${trackingId}.pagination.previous`}
            >
              <ChevronLeft size={16} />
            </button>
            <span>Page {pageIndex + 1} of {table.getPageCount()}</span>
            <button
              type="button"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
              aria-label="Next page"
              data-i7n-name={`${trackingId}.pagination.next`}
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
