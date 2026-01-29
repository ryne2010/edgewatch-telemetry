import * as React from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { cn } from '../lib/utils'

export type DataTableProps<T> = {
  data: T[]
  columns: ColumnDef<T, any>[]
  height?: number
  className?: string
}

export function DataTable<T>(props: DataTableProps<T>) {
  const parentRef = React.useRef<HTMLDivElement>(null)

  const table = useReactTable({
    data: props.data,
    columns: props.columns,
    getCoreRowModel: getCoreRowModel(),
  })

  const rows = table.getRowModel().rows

  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 44,
    overscan: 10,
  })

  return (
    <div
      ref={parentRef}
      className={cn(
        'rounded-md border bg-card text-card-foreground',
        'overflow-auto',
        props.className,
      )}
      style={{ height: props.height ?? 520 }}
    >
      <table className="w-full text-sm">
        <thead className="sticky top-0 z-10 bg-card">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="border-b">
              {hg.headers.map((header) => (
                <th key={header.id} className="px-4 py-2 text-left font-medium text-muted-foreground">
                  {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody
          className="relative"
          style={{ height: rowVirtualizer.getTotalSize() }}
        >
          {rowVirtualizer.getVirtualItems().map((virtualRow) => {
            const row = rows[virtualRow.index]
            return (
              <tr
                key={row.id}
                className="absolute left-0 right-0 border-b last:border-b-0 hover:bg-accent/50"
                style={{ transform: `translateY(${virtualRow.start}px)` }}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-4 py-2 align-middle">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
