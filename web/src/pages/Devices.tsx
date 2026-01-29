import React from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link } from '@tanstack/react-router'
import { useDebouncedValue } from '@tanstack/react-pacer/debouncer'
import { api, type DeviceOut } from '../api'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Input, Page } from '../portfolio-ui'

function statusVariant(status: DeviceOut['status']): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (status === 'online') return 'success'
  if (status === 'offline') return 'destructive'
  return 'secondary'
}

function fmt(ts: string | null) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString()
}

export function DevicesPage() {
  const q = useQuery({ queryKey: ['devices'], queryFn: api.devices, refetchInterval: 10_000 })
  const items = q.data ?? []

  const [searchRaw, setSearchRaw] = React.useState('')
  const [search] = useDebouncedValue(searchRaw, { wait: 200 })

  const filtered = React.useMemo(() => {
    const s = search.trim().toLowerCase()
    if (!s) return items
    return items.filter((d) => `${d.device_id} ${d.display_name}`.toLowerCase().includes(s))
  }, [items, search])

  const cols = React.useMemo<ColumnDef<DeviceOut>[]>(() => {
    return [
      {
        header: 'Device',
        accessorKey: 'device_id',
        cell: (info) => {
          const id = info.getValue() as string
          return (
            <Link to="/devices/$deviceId" params={{ deviceId: id }} className="font-mono text-xs">
              {id}
            </Link>
          )
        },
      },
      { header: 'Name', accessorKey: 'display_name' },
      {
        header: 'Status',
        accessorKey: 'status',
        cell: (info) => <Badge variant={statusVariant(info.getValue() as any)}>{String(info.getValue())}</Badge>,
      },
      {
        header: 'Last seen',
        accessorKey: 'last_seen_at',
        cell: (info) => <span className="text-muted-foreground">{fmt(info.getValue() as any)}</span>,
      },
      {
        header: 'Seconds since',
        accessorKey: 'seconds_since_last_seen',
        cell: (info) => {
          const v = info.getValue() as number | null
          return v == null ? <span className="text-muted-foreground">—</span> : <span className="font-mono text-xs">{v}</span>
        },
      },
    ]
  }, [])

  return (
    <Page
      title="Devices"
      description="Read-only operations dashboard for edge telemetry + heartbeat status."
      actions={
        <div className="flex items-center gap-2">
          <Badge variant="outline">{filtered.length} devices</Badge>
          <Input value={searchRaw} onChange={(e) => setSearchRaw(e.target.value)} placeholder="Search device/name…" />
        </div>
      }
    >
      <Card>
        <CardHeader>
          <CardTitle>Fleet</CardTitle>
          <CardDescription>Virtualized list + debounced search (TanStack Virtual + Pacer).</CardDescription>
        </CardHeader>
        <CardContent>
          {q.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
          {q.isError ? <div className="text-sm text-destructive">Error: {(q.error as Error).message}</div> : null}
          <DataTable<DeviceOut> data={filtered} columns={cols} />
        </CardContent>
      </Card>
    </Page>
  )
}
