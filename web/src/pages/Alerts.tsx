import React from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link } from '@tanstack/react-router'
import { useDebouncedValue } from '@tanstack/react-pacer/debouncer'
import { api, type AlertOut } from '../api'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  DataTable,
  Input,
  Page,
  RangeSlider,
} from '../ui-kit'
import { Sparkline } from '../ui/Sparkline'
import type { Point } from '../ui/LineChart'
import { fmtAlertType, fmtDateTime, timeAgo } from '../utils/format'

type SeverityFilter = 'all' | 'critical' | 'warning' | 'info'

function sevKind(sev: string): SeverityFilter {
  const s = (sev ?? '').toLowerCase()
  if (s === 'critical' || s === 'high' || s === 'error') return 'critical'
  if (s === 'warn' || s === 'warning' || s === 'medium') return 'warning'
  return 'info'
}

function severityVariant(sev: string): 'success' | 'warning' | 'destructive' | 'secondary' {
  const k = sevKind(sev)
  if (k === 'critical') return 'destructive'
  if (k === 'warning') return 'warning'
  return 'secondary'
}

function buildVolumeSeries(rows: AlertOut[], opts?: { hours?: number }) {
  const hours = opts?.hours ?? 7 * 24
  const bucketMs = 60 * 60 * 1000
  const end = Date.now()
  const start = end - hours * bucketMs
  const buckets = Math.max(1, Math.floor((end - start) / bucketMs))

  const counts: Record<'total' | 'critical' | 'warning' | 'info', number[]> = {
    total: Array.from({ length: buckets }, () => 0),
    critical: Array.from({ length: buckets }, () => 0),
    warning: Array.from({ length: buckets }, () => 0),
    info: Array.from({ length: buckets }, () => 0),
  }

  for (const a of rows) {
    const ts = Date.parse(a.created_at)
    if (!Number.isFinite(ts)) continue
    if (ts < start || ts > end) continue
    const i = Math.floor((ts - start) / bucketMs)
    if (i < 0 || i >= buckets) continue
    const k = sevKind(a.severity)
    counts.total[i] += 1
    counts[k][i] += 1
  }

  const toPoints = (arr: number[]): Point[] => {
    return arr.map((y, i) => ({ x: start + i * bucketMs, y }))
  }

  const totals = {
    total: counts.total.reduce((a, b) => a + b, 0),
    critical: counts.critical.reduce((a, b) => a + b, 0),
    warning: counts.warning.reduce((a, b) => a + b, 0),
    info: counts.info.reduce((a, b) => a + b, 0),
  }

  return {
    start,
    end,
    totals,
    series: {
      total: toPoints(counts.total),
      critical: toPoints(counts.critical),
      warning: toPoints(counts.warning),
      info: toPoints(counts.info),
    },
  }
}

export function AlertsPage() {
  const [limit, setLimit] = React.useState(200)
  const [openOnly, setOpenOnly] = React.useState(false)
  const [severity, setSeverity] = React.useState<SeverityFilter>('all')
  const [searchRaw, setSearchRaw] = React.useState('')
  const [search] = useDebouncedValue(searchRaw, { wait: 200 })

  type Cursor = { before: string; before_id: string }

  const q = useInfiniteQuery({
    queryKey: ['alerts', { pageSize: limit, openOnly, severity }],
    initialPageParam: undefined as Cursor | undefined,
    queryFn: ({ pageParam }) =>
      api.alerts({
        limit,
        open_only: openOnly,
        severity: severity === 'all' ? undefined : severity,
        before: pageParam?.before,
        before_id: pageParam?.before_id,
      }),
    getNextPageParam: (lastPage) => {
      if (!lastPage || lastPage.length < limit) return undefined
      const last = lastPage[lastPage.length - 1]
      return { before: last.created_at, before_id: last.id }
    },
  })

  const rows = React.useMemo(() => q.data?.pages.flat() ?? [], [q.data])

  const filtered = React.useMemo(() => {
    const s = search.trim().toLowerCase()
    return rows.filter((a) => {
      if (severity !== 'all' && sevKind(a.severity) !== severity) return false
      if (!s) return true
      return `${a.device_id} ${a.alert_type} ${a.message}`.toLowerCase().includes(s)
    })
  }, [rows, search, severity])

  const openCount = React.useMemo(() => rows.filter((r) => !r.resolved_at).length, [rows])
  const resolvedCount = rows.length - openCount

  const volume = React.useMemo(() => buildVolumeSeries(rows, { hours: 7 * 24 }), [rows])

  const cols = React.useMemo<ColumnDef<AlertOut>[]>(() => {
    return [
      {
        header: 'Severity',
        accessorKey: 'severity',
        cell: (info) => {
          const v = String(info.getValue())
          return <Badge variant={severityVariant(v)}>{v}</Badge>
        },
      },
      {
        header: 'Device',
        accessorKey: 'device_id',
        cell: (info) => {
          const id = String(info.getValue())
          return (
            <Link to="/devices/$deviceId" params={{ deviceId: id }} className="font-mono text-xs">
              {id}
            </Link>
          )
        },
      },
      {
        header: 'Type',
        accessorKey: 'alert_type',
        cell: (info) => <span className="font-mono text-xs">{fmtAlertType(String(info.getValue()))}</span>,
      },
      {
        header: 'Message',
        accessorKey: 'message',
        cell: (info) => <span className="text-muted-foreground">{String(info.getValue())}</span>,
      },
      {
        header: 'Created',
        accessorKey: 'created_at',
        cell: (info) => <span className="text-muted-foreground">{timeAgo(String(info.getValue()))}</span>,
      },
      {
        header: 'Resolved',
        accessorKey: 'resolved_at',
        cell: (info) => {
          const v = info.getValue() as string | null
          return v ? <span className="text-muted-foreground">{fmtDateTime(v)}</span> : <Badge variant="outline">open</Badge>
        },
      },
    ]
  }, [])

  return (
    <Page
      title="Alerts"
      description="Paginated alert feed with local filtering (severity, open/resolved) and debounced search."
      actions={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Badge variant="outline">{filtered.length} shown</Badge>
          <Button variant="outline" size="sm" onClick={() => q.refetch()} disabled={q.isFetching}>
            Refresh
          </Button>
          <Input value={searchRaw} onChange={(e) => setSearchRaw(e.target.value)} placeholder="Search device/type/message…" />
        </div>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle>Total</CardTitle>
            <CardDescription>Loaded from API</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{rows.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Open</CardTitle>
            <CardDescription>Unresolved</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{openCount}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Resolved</CardTitle>
            <CardDescription>Resolved in the list</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{resolvedCount}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Page size</CardTitle>
            <CardDescription>Each page fetches this many rows</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="font-mono text-xs text-muted-foreground">{limit} rows</div>
              <RangeSlider
                min={50}
                max={500}
                step={50}
                value={limit}
                onChange={setLimit}
                label="Per page"
                format={(v) => String(v)}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Alert volume</CardTitle>
          <CardDescription>
            Rolling 7-day hourly buckets (based on the loaded dataset). Load more pages for more accurate volume.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border bg-background p-3">
              <div className="text-sm font-medium">Total</div>
              <div className="text-2xl font-semibold tracking-tight">{volume.totals.total}</div>
              <div className="mt-2 text-primary">
                <Sparkline points={volume.series.total} height={56} ariaLabel="total alerts sparkline" />
              </div>
            </div>

            <div className="rounded-lg border bg-background p-3">
              <div className="text-sm font-medium">Critical</div>
              <div className="text-2xl font-semibold tracking-tight">{volume.totals.critical}</div>
              <div className="mt-2 text-destructive">
                <Sparkline points={volume.series.critical} height={56} ariaLabel="critical alerts sparkline" />
              </div>
            </div>

            <div className="rounded-lg border bg-background p-3">
              <div className="text-sm font-medium">Warning</div>
              <div className="text-2xl font-semibold tracking-tight">{volume.totals.warning}</div>
              <div className="mt-2 text-amber-600">
                <Sparkline points={volume.series.warning} height={56} ariaLabel="warning alerts sparkline" />
              </div>
            </div>

            <div className="rounded-lg border bg-background p-3">
              <div className="text-sm font-medium">Info</div>
              <div className="text-2xl font-semibold tracking-tight">{volume.totals.info}</div>
              <div className="mt-2 text-muted-foreground">
                <Sparkline points={volume.series.info} height={56} ariaLabel="info alerts sparkline" />
              </div>
            </div>
          </div>

          <div className="mt-3 text-xs text-muted-foreground">
            Window: {new Date(volume.start).toLocaleString()} → {new Date(volume.end).toLocaleString()}.
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Feed</CardTitle>
          <CardDescription>Use filters to focus on what matters.</CardDescription>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button variant={openOnly ? 'default' : 'outline'} size="sm" onClick={() => setOpenOnly((v) => !v)}>
              {openOnly ? 'Open only' : 'All (open + resolved)'}
            </Button>
            <Button variant={severity === 'all' ? 'default' : 'outline'} size="sm" onClick={() => setSeverity('all')}>
              All severities
            </Button>
            <Button variant={severity === 'critical' ? 'default' : 'outline'} size="sm" onClick={() => setSeverity('critical')}>
              Critical
            </Button>
            <Button variant={severity === 'warning' ? 'default' : 'outline'} size="sm" onClick={() => setSeverity('warning')}>
              Warning
            </Button>
            <Button variant={severity === 'info' ? 'default' : 'outline'} size="sm" onClick={() => setSeverity('info')}>
              Info
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {q.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
          {q.isError ? <div className="text-sm text-destructive">Error: {(q.error as Error).message}</div> : null}
          <DataTable<AlertOut>
            data={filtered}
            columns={cols}
            enableSorting
            initialSorting={[{ id: 'created_at', desc: true }]}
            emptyState="No alerts match your filters."
          />

          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs text-muted-foreground">
              {q.hasNextPage ? 'More available…' : 'End of feed.'}
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={!q.hasNextPage || q.isFetchingNextPage}
              onClick={() => q.fetchNextPage()}
            >
              {q.isFetchingNextPage ? 'Loading…' : 'Load more'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </Page>
  )
}
