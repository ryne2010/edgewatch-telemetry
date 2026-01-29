import React from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link } from '@tanstack/react-router'
import { useDebouncedValue } from '@tanstack/react-pacer/debouncer'
import { api, type AlertOut } from '../api'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Page, RangeSlider } from '../portfolio-ui'

function fmt(ts: string | null) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString()
}

function severityVariant(sev: string): 'success' | 'warning' | 'destructive' | 'secondary' {
  const s = sev.toLowerCase()
  if (s.includes('critical') || s.includes('high')) return 'destructive'
  if (s.includes('medium') || s.includes('warn')) return 'warning'
  if (s.includes('low') || s.includes('info')) return 'secondary'
  return 'secondary'
}

export function AlertsPage() {
  const [limit, setLimit] = React.useState(100)
  const [debouncedLimit] = useDebouncedValue(limit, { wait: 150 })

  const q = useQuery({
    queryKey: ['alerts', debouncedLimit],
    queryFn: () => api.alerts(debouncedLimit),
    refetchInterval: 10_000,
  })

  const items = q.data ?? []

  const cols = React.useMemo<ColumnDef<AlertOut>[]>(() => {
    return [
      { header: 'Created', accessorKey: 'created_at', cell: (info) => <span className="text-muted-foreground">{fmt(info.getValue() as any)}</span> },
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
      { header: 'Type', accessorKey: 'alert_type' },
      {
        header: 'Severity',
        accessorKey: 'severity',
        cell: (info) => <Badge variant={severityVariant(String(info.getValue()))}>{String(info.getValue())}</Badge>,
      },
      { header: 'Message', accessorKey: 'message', cell: (info) => <span className="text-muted-foreground">{String(info.getValue())}</span> },
      { header: 'Resolved', accessorKey: 'resolved_at', cell: (info) => <span className="text-muted-foreground">{fmt(info.getValue() as any)}</span> },
    ]
  }, [])

  return (
    <Page
      title="Alerts"
      description="Alert feed with routing-rule-friendly metadata (severity, device, resolved state)."
      actions={
        <div className="flex items-center gap-2">
          <Badge variant="outline">{items.length} alerts</Badge>
          <Badge variant="secondary">limit: {debouncedLimit}</Badge>
        </div>
      }
    >
      <Card>
        <CardHeader>
          <CardTitle>Recent alerts</CardTitle>
          <CardDescription>Slider uses TanStack Ranger; debounce uses TanStack Pacer.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <RangeSlider min={10} max={200} step={10} value={limit} onChange={setLimit} label="Limit" />
          {q.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
          {q.isError ? <div className="text-sm text-destructive">Error: {(q.error as Error).message}</div> : null}
          <DataTable<AlertOut> data={items} columns={cols} />
        </CardContent>
      </Card>
    </Page>
  )
}
