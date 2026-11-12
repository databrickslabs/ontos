import * as React from "react";
import {
  ColumnDef,
  ColumnFiltersState,
  SortingState,
  VisibilityState,
  PaginationState,
  OnChangeFn,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  RowSelectionState,
  Row,
  Table as TanStackTable,
} from "@tanstack/react-table";

import { ChevronDown, Loader2 } from "lucide-react";
import { useTranslation } from 'react-i18next';

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent } from "./card";
import { cn } from "@/lib/utils";

// Double angle bracket svgs for pagination
const ChevronsLeft = () => <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4"><path fillRule="evenodd" d="M15.79 14.77a.75.75 0 01-1.06 0l-4.25-4.25a.75.75 0 010-1.06l4.25-4.25a.75.75 0 111.06 1.06L12.31 10l3.48 3.71a.75.75 0 010 1.06zm-6.75 0a.75.75 0 01-1.06 0l-4.25-4.25a.75.75 0 010-1.06l4.25-4.25a.75.75 0 111.06 1.06L5.56 10l3.48 3.71a.75.75 0 010 1.06z" clipRule="evenodd" /></svg>;
const ChevronsRight = () => <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4"><path fillRule="evenodd" d="M4.21 5.23a.75.75 0 011.06 0l4.25 4.25a.75.75 0 010 1.06l-4.25 4.25a.75.75 0 11-1.06-1.06L7.94 10 4.21 6.29a.75.75 0 010-1.06zm6.75 0a.75.75 0 011.06 0l4.25 4.25a.75.75 0 010 1.06l-4.25 4.25a.75.75 0 11-1.06-1.06L14.69 10l-3.72-3.71a.75.75 0 010-1.06z" clipRule="evenodd" /></svg>;


/** Minimum width (px) kept by a column without a declared size in `fixedLayout`. */
const FLEXIBLE_COLUMN_MIN_WIDTH = 130;

interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
  searchColumn?: string;
  toolbarActions?: React.ReactNode;
  bulkActions?: (selectedRows: TData[]) => React.ReactNode;
  onRowClick?: (row: Row<TData>) => void;
  storageKey?: string;
  /** Show the row-select checkbox column and the "N of M rows selected" line.
   *  Defaults to true; turn off for read-only tables that have no row actions. */
  selectable?: boolean;
  /** Compact cells and header (less padding, shorter rows). Defaults to false. */
  dense?: boolean;
  /** `table-layout: fixed`: columns that declare a `size` get that width in px, the rest share
   *  the remaining space, and long content truncates instead of widening the table. Defaults to false. */
  fixedLayout?: boolean;
  defaultSortColumn?: string;
  defaultSortDirection?: 'asc' | 'desc';
  isLoading?: boolean;
  rowSelection?: RowSelectionState;
  onRowSelectionChange?: (rowSelection: RowSelectionState) => void;
  // Server-side pagination
  manualPagination?: boolean;
  pageCount?: number;
  paginationState?: PaginationState;
  onPaginationChange?: OnChangeFn<PaginationState>;
  // Controlled search (for server-side filtering)
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  // Controlled sorting. When `sorting` is provided it is the source of truth
  // and the `storageKey` localStorage persistence is not used for sorting.
  sorting?: SortingState;
  onSortingChange?: (sorting: SortingState) => void;
  // Controlled page size (client-side pagination only; ignored when
  // `manualPagination` is set). The page index stays internal.
  pageSize?: number;
  onPageSizeChange?: (pageSize: number) => void;
  // Optional footer rendered inside the same <table> (in a <tfoot>) so its
  // cells align with the columns. Pass a function to read the table instance,
  // e.g. to render one cell per visible column.
  footer?: React.ReactNode | ((table: TanStackTable<TData>) => React.ReactNode);
}

export function DataTable<TData, TValue>({
  columns,
  data,
  searchColumn,
  toolbarActions,
  bulkActions,
  onRowClick,
  storageKey,
  selectable = true,
  dense = false,
  fixedLayout = false,
  defaultSortColumn,
  defaultSortDirection = 'asc',
  isLoading = false,
  rowSelection: controlledRowSelection,
  onRowSelectionChange,
  manualPagination = false,
  pageCount,
  paginationState,
  onPaginationChange,
  searchValue,
  onSearchChange,
  sorting: controlledSorting,
  onSortingChange,
  pageSize: controlledPageSize,
  onPageSizeChange,
  footer,
}: DataTableProps<TData, TValue>) {
  const { t } = useTranslation(['data-table', 'common']);
  
  // Helper function to detect the default sort column from columns
  const detectDefaultSortColumn = React.useCallback((): string | null => {
    if (defaultSortColumn) return defaultSortColumn;
    
    // Look for common name-like columns
    const nameColumns = ['name', 'title', 'info.title'];
    for (const col of columns) {
      const colId = typeof col.id === 'string' ? col.id : '';
      const accessorKey = (col as any).accessorKey;
      
      if (nameColumns.includes(colId) || nameColumns.includes(accessorKey)) {
        return colId || accessorKey;
      }
    }
    
    return null;
  }, [columns, defaultSortColumn]);

  // Initialize sorting state with localStorage and default sorting
  const isSortingControlled = controlledSorting !== undefined;
  const getInitialSorting = React.useCallback((): SortingState => {
    // Controlled sorting: the parent owns the state, nothing to load.
    if (isSortingControlled) return [];
    // Try to load from localStorage if storageKey is provided
    if (storageKey) {
      try {
        const stored = localStorage.getItem(storageKey);
        if (stored) {
          const parsed = JSON.parse(stored);
          if (Array.isArray(parsed) && parsed.length > 0) {
            return parsed;
          }
        }
      } catch (error) {
        console.warn('Failed to load sorting from localStorage:', error);
      }
    }
    
    // Fall back to default sorting
    const defaultColumn = detectDefaultSortColumn();
    if (defaultColumn) {
      return [{ id: defaultColumn, desc: defaultSortDirection === 'desc' }];
    }
    
    return [];
  }, [isSortingControlled, storageKey, detectDefaultSortColumn, defaultSortDirection]);

  const [internalSorting, setInternalSorting] = React.useState<SortingState>(getInitialSorting);
  const sorting = isSortingControlled ? controlledSorting : internalSorting;
  const setSorting: OnChangeFn<SortingState> = React.useCallback((updater) => {
    if (isSortingControlled) {
      onSortingChange?.(typeof updater === 'function' ? updater(sorting) : updater);
    } else {
      setInternalSorting(updater);
    }
  }, [isSortingControlled, onSortingChange, sorting]);

  // Controlled page size (client-side pagination only). The page index is
  // kept here; page size changes are reported to the parent.
  const isPageSizeControlled = controlledPageSize !== undefined && !manualPagination;
  const [internalPageIndex, setInternalPageIndex] = React.useState(0);
  const handleControlledPagination: OnChangeFn<PaginationState> = React.useCallback((updater) => {
    const prev = { pageIndex: internalPageIndex, pageSize: controlledPageSize ?? 10 };
    const next = typeof updater === 'function' ? updater(prev) : updater;
    setInternalPageIndex(next.pageIndex);
    if (next.pageSize !== prev.pageSize) {
      onPageSizeChange?.(next.pageSize);
    }
  }, [internalPageIndex, controlledPageSize, onPageSizeChange]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({});
  const [internalRowSelection, setInternalRowSelection] = React.useState<RowSelectionState>({});
  const [globalFilter, setGlobalFilter] = React.useState("");

  // Use controlled or internal row selection state
  const isControlled = controlledRowSelection !== undefined;
  const rowSelection = isControlled ? controlledRowSelection : internalRowSelection;
  const setRowSelection = React.useCallback((updater: RowSelectionState | ((prev: RowSelectionState) => RowSelectionState)) => {
    const newValue = typeof updater === 'function' ? updater(rowSelection) : updater;
    if (isControlled && onRowSelectionChange) {
      onRowSelectionChange(newValue);
    } else {
      setInternalRowSelection(newValue);
    }
  }, [isControlled, onRowSelectionChange, rowSelection]);

  // Persist sorting to localStorage whenever it changes
  React.useEffect(() => {
    if (!isSortingControlled && storageKey && sorting.length > 0) {
      try {
        localStorage.setItem(storageKey, JSON.stringify(sorting));
      } catch (error) {
        console.warn('Failed to save sorting to localStorage:', error);
      }
    }
  }, [sorting, storageKey, isSortingControlled]);

  // Add default select column (omitted when selectable is false)
  const tableColumns: ColumnDef<TData, TValue>[] = React.useMemo(() => [
    ...(!selectable ? [] : [{
      id: "select",
      header: ({ table }) => (
        <Checkbox
          checked={table.getIsAllPageRowsSelected() || (table.getIsSomePageRowsSelected() && "indeterminate")}
          onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
          aria-label={t('common:dataTable.selectAll')}
          className="translate-y-[2px]"
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
          aria-label={t('common:dataTable.selectRow')}
          className="translate-y-[2px]"
        />
      ),
      enableSorting: false,
      enableHiding: false,
    } as ColumnDef<TData, TValue>]),
    ...columns,
  ], [columns, selectable]);

  const table = useReactTable({
    data,
    columns: tableColumns,
    autoResetPageIndex: false,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    ...(manualPagination
      ? { manualPagination: true, pageCount: pageCount ?? -1 }
      : { getPaginationRowModel: getPaginationRowModel() }),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    onGlobalFilterChange: setGlobalFilter,
    getRowId: (row: TData) => (row as any).id ?? undefined,
    ...(manualPagination && onPaginationChange
      ? { onPaginationChange }
      : {}),
    ...(isPageSizeControlled
      ? { onPaginationChange: handleControlledPagination }
      : {}),
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      rowSelection,
      globalFilter,
      ...(manualPagination && paginationState ? { pagination: paginationState } : {}),
      ...(isPageSizeControlled
        ? { pagination: { pageIndex: internalPageIndex, pageSize: controlledPageSize } }
        : {}),
    },
    initialState: {
      pagination: {
        pageSize: paginationState?.pageSize ?? 10,
      },
    },
  });

  // Reset pagination to first page when filters change (needed because autoResetPageIndex is false)
  const prevGlobalFilter = React.useRef(globalFilter);
  const prevColumnFilters = React.useRef(columnFilters);
  React.useEffect(() => {
    const filtersChanged =
      prevGlobalFilter.current !== globalFilter ||
      prevColumnFilters.current !== columnFilters;
    prevGlobalFilter.current = globalFilter;
    prevColumnFilters.current = columnFilters;
    if (filtersChanged) {
      table.setPageIndex(0);
    }
  }, [globalFilter, columnFilters, table]);

  // Controlled page size: a controlled search does not touch globalFilter, so
  // go back to the first page when it changes, and clamp the page index when
  // the data shrinks below the current page.
  const prevSearchValue = React.useRef(searchValue);
  const controlledPageCount = isPageSizeControlled ? table.getPageCount() : 0;
  React.useEffect(() => {
    if (!isPageSizeControlled) return;
    if (prevSearchValue.current !== searchValue) {
      prevSearchValue.current = searchValue;
      setInternalPageIndex(0);
      return;
    }
    const maxIndex = Math.max(0, controlledPageCount - 1);
    if (internalPageIndex > maxIndex) setInternalPageIndex(maxIndex);
  }, [isPageSizeControlled, searchValue, controlledPageCount, internalPageIndex]);

  // Fixed layout: only columns whose definition declares a `size` get that width. TanStack merges a
  // default size of 150 into every resolved column, so the declared sizes are read from `columns`.
  const declaredSizes = React.useMemo(() => {
    const sizes = new Map<string, number>();
    columns.forEach((c) => {
      const id = c.id ?? (c as { accessorKey?: string }).accessorKey;
      if (id && typeof c.size === 'number') sizes.set(String(id), c.size);
    });
    return sizes;
  }, [columns]);
  const columnWidthStyle = (columnId: string): React.CSSProperties | undefined =>
    fixedLayout && declaredSizes.has(columnId) ? { width: declaredSizes.get(columnId) } : undefined;
  // Below this width the table scrolls inside its wrapper instead of squeezing the flexible columns
  // (each flexible column keeps at least FLEXIBLE_COLUMN_MIN_WIDTH px).
  const fixedTableMinWidth = fixedLayout
    ? Array.from(declaredSizes.values()).reduce((sum, w) => sum + w, 0) +
      (columns.length - declaredSizes.size) * FLEXIBLE_COLUMN_MIN_WIDTH
    : undefined;

  const selectedRowsData = React.useMemo(() =>
    table.getFilteredSelectedRowModel().rows.map(row => row.original),
    [rowSelection, table]
  );

  // Function to format column ID for display
  const formatColumnId = (id: string): string => {
    return id
      .replace(/_/g, ' ')
      .replace(/\./g, ' > ')
      .replace(/([A-Z])/g, ' $1')
      .trim()
      // Capitalize first letter of each word
      .replace(/\b\w/g, char => char.toUpperCase());
  };

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Input
            placeholder={`${t('filter')} ${searchColumn ? formatColumnId(searchColumn).toLowerCase() + 's' : t('items')}...`}
            value={onSearchChange ? (searchValue ?? "") : (globalFilter ?? "")}
            onChange={(event) =>
              onSearchChange
                ? onSearchChange(event.target.value)
                : setGlobalFilter(event.target.value)
            }
            className="max-w-sm h-9"
          />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="ml-auto h-9">
                {t('columns')} <ChevronDown className="ml-2 h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {table
                .getAllColumns()
                .filter((column) => column.getCanHide())
                .map((column) => {
                  return (
                    <DropdownMenuCheckboxItem
                      key={column.id}
                      checked={column.getIsVisible()}
                      onCheckedChange={(value) =>
                        column.toggleVisibility(!!value)
                      }
                    >
                      {formatColumnId(column.id)}
                    </DropdownMenuCheckboxItem>
                  );
                })}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <div className="flex items-center gap-2">
          {toolbarActions}
        </div>
      </div>

      {/* Bulk Actions */}
      {Object.keys(rowSelection).length > 0 && bulkActions && (
        <div className="flex items-center justify-end gap-2 border-t pt-2 mt-2">
          <span className="text-sm text-muted-foreground">
             {Object.keys(rowSelection).length} {t('selected')}
          </span>
          {bulkActions(selectedRowsData)}
        </div>
      )}

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table
              className={fixedLayout ? 'table-fixed' : undefined}
              style={fixedTableMinWidth ? { minWidth: fixedTableMinWidth } : undefined}
            >
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => {
                      return (
                        <TableHead
                          key={header.id}
                          colSpan={header.colSpan}
                          className={dense ? 'h-9 px-3' : undefined}
                          style={columnWidthStyle(header.column.id)}
                        >
                          {header.isPlaceholder
                            ? null
                            : flexRender(
                                header.column.columnDef.header,
                                header.getContext()
                              )}
                        </TableHead>
                      );
                    })}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <TableRow>
                    <TableCell
                      colSpan={tableColumns.length}
                      className="h-24 text-center"
                    >
                      <div className="flex justify-center items-center">
                        <Loader2 className="animate-spin h-8 w-8 text-primary" />
                      </div>
                    </TableCell>
                  </TableRow>
                ) : table.getRowModel().rows?.length ? (
                  table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      data-state={row.getIsSelected() && "selected"}
                      onClick={(e) => {
                        // Prevent row click if clicking inside an action cell or checkbox
                        const target = e.target as HTMLElement;
                         if (target.closest('[role="checkbox"]') || target.closest('[data-action-cell="true"]')) {
                            return;
                         }
                         onRowClick?.(row)
                      }}
                      className={cn(
                        onRowClick && "cursor-pointer hover:bg-muted/50"
                      )}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell
                           key={cell.id}
                           className={dense ? 'px-3 py-2' : undefined}
                           // Mark action cells to prevent row click
                           {...(cell.column.id === 'actions' ? { 'data-action-cell': 'true' } : {})}
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell
                      colSpan={tableColumns.length}
                      className="h-24 text-center"
                    >
                      {t('noResults')}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
              {footer !== undefined && footer !== null && (
                <TableFooter className="bg-muted/40 text-foreground">
                  {typeof footer === 'function' ? footer(table) : footer}
                </TableFooter>
              )}
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Pagination */}
      <div className="flex items-center justify-between space-x-2 pt-4">
        <div className="flex-1 text-sm text-muted-foreground">
          {selectable && (
            <>
              {table.getFilteredSelectedRowModel().rows.length} {t('of')}{" "}
              {table.getFilteredRowModel().rows.length} {t('rowsSelected')}
            </>
          )}
        </div>
        <div className="flex items-center space-x-6 lg:space-x-8">
          <div className="flex items-center space-x-2">
            <p className="text-sm font-medium">{t('pagination.rowsPerPage')}</p>
            <Select
              value={`${table.getState().pagination.pageSize}`}
              onValueChange={(value) => {
                table.setPageSize(Number(value))
              }}
            >
              <SelectTrigger className="h-8 w-[70px]">
                <SelectValue placeholder={table.getState().pagination.pageSize} />
              </SelectTrigger>
              <SelectContent side="top">
                {[10, 20, 30, 40, 50].map((pageSize) => (
                  <SelectItem key={pageSize} value={`${pageSize}`}>
                    {pageSize}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex w-[100px] items-center justify-center text-sm font-medium">
            {t('pagination.page')} {table.getState().pagination.pageIndex + 1} {t('of')}{" "}
            {table.getPageCount() ?? 0} {/* Handle zero pages */}
          </div>
          <div className="flex items-center space-x-2">
            <Button
              variant="outline"
              className="hidden h-8 w-8 p-0 lg:flex"
              onClick={() => table.setPageIndex(0)}
              disabled={!table.getCanPreviousPage()}
            >
              <span className="sr-only">{t('pagination.goToFirstPage')}</span>
              <ChevronsLeft />
            </Button>
            <Button
              variant="outline"
              className="h-8 w-8 p-0"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              <span className="sr-only">{t('pagination.goToPreviousPage')}</span>
              <ChevronDown className="h-4 w-4 rotate-90" />
            </Button>
            <Button
              variant="outline"
              className="h-8 w-8 p-0"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              <span className="sr-only">{t('pagination.goToNextPage')}</span>
              <ChevronDown className="h-4 w-4 -rotate-90" />
            </Button>
            <Button
              variant="outline"
              className="hidden h-8 w-8 p-0 lg:flex"
              onClick={() => table.setPageIndex(table.getPageCount() - 1)}
              disabled={!table.getCanNextPage()}
            >
              <span className="sr-only">{t('pagination.goToLastPage')}</span>
              <ChevronsRight />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
} 