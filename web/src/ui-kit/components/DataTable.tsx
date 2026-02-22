import * as React from 'react'
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from '@tanstack/react-table'
import { cn } from '../lib/utils'

export type DataTableProps<T> = {
  data: T[]
  columns: ColumnDef<T, any>[]
  height?: number
  className?: string
  enableSorting?: boolean
  initialSorting?: SortingState
  onRowClick?: (row: T) => void
  emptyState?: React.ReactNode
}

export function DataTable<T>(props: DataTableProps<T>) {
  const [sorting, setSorting] = React.useState<SortingState>(() => props.initialSorting ?? [])

  const table = useReactTable({
    data: props.data,
    columns: props.columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: props.enableSorting ? getSortedRowModel() : undefined,
    onSortingChange: props.enableSorting ? setSorting : undefined,
    state: props.enableSorting ? { sorting } : undefined,
  })

  const rows = table.getRowModel().rows

  return (
    <div
      className={cn(
        'rounded-md border bg-card text-card-foreground',
        'overflow-auto',
        props.className,
      )}
      style={{ height: props.height ?? 520 }}
    >
      <table className="min-w-full table-auto text-sm">
        <thead className="sticky top-0 z-10 bg-card">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="border-b">
              {hg.headers.map((header) => (
                <th
                  key={header.id}
                  className={cn(
                    'whitespace-nowrap px-4 py-2 text-left align-middle font-medium text-muted-foreground',
                    props.enableSorting && header.column.getCanSort() ? 'cursor-pointer select-none' : '',
                  )}
                  onClick={props.enableSorting ? header.column.getToggleSortingHandler() : undefined}
                  aria-sort={
                    !props.enableSorting
                      ? undefined
                      : header.column.getIsSorted() === 'asc'
                        ? 'ascending'
                        : header.column.getIsSorted() === 'desc'
                          ? 'descending'
                          : 'none'
                  }
                >
                  <div className="flex items-center gap-2">
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                    {props.enableSorting && header.column.getCanSort() ? (
                      <span className="text-xs text-muted-foreground">
                        {header.column.getIsSorted() === 'asc'
                          ? '▲'
                          : header.column.getIsSorted() === 'desc'
                            ? '▼'
                            : ''}
                      </span>
                    ) : null}
                  </div>
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={table.getVisibleLeafColumns().length}
                className="px-4 py-8 text-center text-sm text-muted-foreground"
              >
                {props.emptyState ?? 'No results.'}
              </td>
            </tr>
          ) : null}

          {rows.map((row) => (
            <tr
              key={row.id}
              className={cn(
                'border-b last:border-b-0',
                props.onRowClick ? 'cursor-pointer hover:bg-accent/50' : 'hover:bg-accent/50',
              )}
              onClick={props.onRowClick ? () => props.onRowClick?.(row.original) : undefined}
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-4 py-2 align-top [overflow-wrap:anywhere]">
                  <div className="min-w-0">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </div>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
