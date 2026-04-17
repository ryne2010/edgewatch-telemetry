import React from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link, useLocation, useNavigate } from '@tanstack/react-router'
import { useDebouncedValue } from '@tanstack/react-pacer/debouncer'
import { useAppSettings } from '../app/settings'
import { api, type AlertOut, type NotificationEventOut } from '../api'
import { useAdminAccess } from '../hooks/useAdminAccess'
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
  Label,
  Page,
  RangeSlider,
} from '../ui-kit'
import { Sparkline } from '../ui/Sparkline'
import type { Point } from '../ui/LineChart'
import {
  buildAlertsSearch,
  buildHref,
  type ResolutionFilter,
  type SeverityFilter,
  normalizeSearchString,
  parseAlertsSearch,
} from '../utils/filterUrlState'
import { fmtAlertType, fmtDateTime, timeAgo } from '../utils/format'
type SeverityKind = Exclude<SeverityFilter, 'all'>

function sevKind(sev: string): SeverityKind {
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

function routingVariant(decision: string, delivered: boolean): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (delivered) return 'success'
  const d = (decision ?? '').toLowerCase()
  if (d.includes('dedupe') || d.includes('throttle') || d.includes('quiet')) return 'warning'
  if (d.includes('error') || d.includes('failed')) return 'destructive'
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

  const toPoints = (arr: number[]): Point[] => arr.map((y, i) => ({ x: start + i * bucketMs, y }))

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
  const navigate = useNavigate()
  const pathname = useLocation({ select: (s) => s.pathname })
  const searchStr = useLocation({ select: (s) => s.searchStr })
  const { adminKey } = useAppSettings()
  const qc = useQueryClient()

  const healthQ = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })

  const adminEnabled = Boolean(healthQ.data?.features?.admin?.enabled)
  const adminAuthMode = String(healthQ.data?.features?.admin?.auth_mode ?? 'key').toLowerCase()
  const { adminAccess, adminCred } = useAdminAccess({
    adminEnabled,
    adminAuthMode,
    adminKey,
  })

  React.useEffect(() => {
    // Refresh cached admin queries when key/mode changes to avoid sticky auth errors.
    qc.invalidateQueries({ queryKey: ['admin'] })
  }, [qc, adminAuthMode, adminKey])

  const initialSearchFilters = React.useMemo(() => parseAlertsSearch(searchStr), [searchStr])
  const [limit, setLimit] = React.useState(initialSearchFilters.limit)
  const [resolutionFilter, setResolutionFilter] = React.useState<ResolutionFilter>(initialSearchFilters.resolutionFilter)
  const [severity, setSeverity] = React.useState<SeverityFilter>(initialSearchFilters.severityFilter)
  const [typeFilter, setTypeFilter] = React.useState(initialSearchFilters.typeFilter)
  const [deviceFilterRaw, setDeviceFilterRaw] = React.useState(initialSearchFilters.deviceFilter)
  const [deviceFilter] = useDebouncedValue(deviceFilterRaw, { wait: 250 })
  const [searchRaw, setSearchRaw] = React.useState(initialSearchFilters.search)
  const [search] = useDebouncedValue(searchRaw, { wait: 200 })
  const feedRef = React.useRef<HTMLDivElement | null>(null)

  React.useEffect(() => {
    const parsed = parseAlertsSearch(searchStr)
    setLimit(parsed.limit)
    setResolutionFilter(parsed.resolutionFilter)
    setSeverity(parsed.severityFilter)
    setTypeFilter(parsed.typeFilter)
    setDeviceFilterRaw(parsed.deviceFilter)
    setSearchRaw(parsed.search)
  }, [searchStr])

  React.useEffect(() => {
    const nextSearch = buildAlertsSearch({
      resolutionFilter,
      severityFilter: severity,
      typeFilter,
      deviceFilter,
      search,
      limit,
    })
    if (nextSearch === normalizeSearchString(searchStr)) return
    navigate({ href: buildHref(pathname, nextSearch), replace: true })
  }, [resolutionFilter, severity, typeFilter, deviceFilter, search, limit, searchStr, pathname, navigate])

  type Cursor = { before: string; before_id: string }
  const queryOpenOnly = resolutionFilter === 'open'

  const q = useInfiniteQuery({
    queryKey: ['alerts', { pageSize: limit, resolutionFilter, severity, typeFilter, deviceFilter, search }],
    initialPageParam: undefined as Cursor | undefined,
    queryFn: ({ pageParam }) =>
      api.alerts({
        limit,
        open_only: queryOpenOnly,
        severity: severity === 'all' ? undefined : severity,
        alert_type: typeFilter === 'all' ? undefined : typeFilter,
        device_id: deviceFilter.trim() || undefined,
        q: search.trim() || undefined,
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

  const typeOptions = React.useMemo(() => {
    const out = new Set<string>()
    for (const r of rows) out.add(r.alert_type)
    return Array.from(out).sort((a, b) => a.localeCompare(b))
  }, [rows])

  const filtered = React.useMemo(() => {
    return rows.filter((a) => {
      if (resolutionFilter === 'open' && a.resolved_at) return false
      if (resolutionFilter === 'resolved' && !a.resolved_at) return false
      return true
    })
  }, [rows, resolutionFilter])

  const scrollToFeed = React.useCallback(() => {
    feedRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  const applyResolutionFromTile = React.useCallback(
    (filter: ResolutionFilter) => {
      setResolutionFilter(filter)
      scrollToFeed()
    },
    [scrollToFeed],
  )

  const summaryCardProps = React.useCallback(
    (onActivate: () => void) => ({
      role: 'button' as const,
      tabIndex: 0,
      className:
        'cursor-pointer transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
      onClick: (event: React.MouseEvent<HTMLDivElement>) => {
        const interactive = (event.target as HTMLElement | null)?.closest(
          'a,button,input,textarea,select,[role=\"button\"],[role=\"slider\"]',
        )
        if (interactive && interactive !== event.currentTarget) return
        onActivate()
      },
      onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => {
        if (event.key !== 'Enter' && event.key !== ' ') return
        const interactive = (event.target as HTMLElement | null)?.closest(
          'a,button,input,textarea,select,[role=\"button\"],[role=\"slider\"]',
        )
        if (interactive && interactive !== event.currentTarget) return
        event.preventDefault()
        onActivate()
      },
    }),
    [],
  )

  const openCount = React.useMemo(() => filtered.filter((r) => !r.resolved_at).length, [filtered])
  const resolvedCount = filtered.length - openCount

  const volume = React.useMemo(() => buildVolumeSeries(filtered, { hours: 7 * 24 }), [filtered])

  const notificationsQ = useQuery({
    queryKey: ['admin', 'notifications', 'alertsPage', deviceFilter],
    queryFn: () => api.admin.notifications(adminCred, { device_id: deviceFilter.trim() || undefined, limit: 500 }),
    enabled: adminAccess,
    refetchInterval: 15_000,
  })
  const notificationByAlertId = React.useMemo(() => {
    const out = new Map<string, NotificationEventOut>()
    for (const n of notificationsQ.data ?? []) {
      if (!n.alert_id) continue
      const existing = out.get(n.alert_id)
      if (!existing || Date.parse(n.created_at) > Date.parse(existing.created_at)) out.set(n.alert_id, n)
    }
    return out
  }, [notificationsQ.data])

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
        header: 'Routing',
        id: 'routing',
        cell: (info) => {
          const n = notificationByAlertId.get(info.row.original.id)
          if (!n) return <span className="text-xs text-muted-foreground">—</span>
          return (
            <div className="space-y-1">
              <Badge variant={routingVariant(n.decision, n.delivered)}>{n.decision}</Badge>
              <div className="max-w-[14rem] truncate text-[11px] text-muted-foreground">{n.reason}</div>
            </div>
          )
        },
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
  }, [notificationByAlertId])

  return (
    <Page
      title="Alerts"
      description="Alert feed with device/type/severity filters."
      actions={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Badge variant="outline">{filtered.length} shown</Badge>
          <Button variant="outline" size="sm" onClick={() => q.refetch()} disabled={q.isFetching}>
            Refresh
          </Button>
          <Input value={searchRaw} onChange={(e) => setSearchRaw(e.target.value)} placeholder="Search device/type/message..." />
        </div>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card {...summaryCardProps(() => applyResolutionFromTile('all'))}>
          <CardHeader>
            <CardTitle>Total</CardTitle>
            <CardDescription>Show all rows in Feed</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{filtered.length}</div>
          </CardContent>
        </Card>
        <Card {...summaryCardProps(() => applyResolutionFromTile('open'))}>
          <CardHeader>
            <CardTitle>Open</CardTitle>
            <CardDescription>Open, unresolved</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{openCount}</div>
          </CardContent>
        </Card>
        <Card {...summaryCardProps(() => applyResolutionFromTile('resolved'))}>
          <CardHeader>
            <CardTitle>Resolved</CardTitle>
            <CardDescription>Resolved rows only</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{resolvedCount}</div>
          </CardContent>
        </Card>
        <Card {...summaryCardProps(scrollToFeed)}>
          <CardHeader>
            <CardTitle>Page size</CardTitle>
            <CardDescription>Jump to Feed controls</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="font-mono text-xs text-muted-foreground">{limit} rows</div>
              <RangeSlider min={50} max={500} step={50} value={limit} onChange={setLimit} label="Per page" format={(v) => String(v)} />
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Alert volume</CardTitle>
          <CardDescription>
            Rolling 7-day hourly buckets (based on the currently shown dataset). Load more pages for broader coverage.
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
            Window: {new Date(volume.start).toLocaleString()} {'->'} {new Date(volume.end).toLocaleString()}.
          </div>
        </CardContent>
      </Card>

      <div ref={feedRef}>
        <Card>
          <CardHeader>
            <CardTitle>Feed</CardTitle>
            <CardDescription>Use filters to focus on active devices and relevant alert types.</CardDescription>
            <div className="mt-3 space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant={resolutionFilter === 'all' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setResolutionFilter('all')}
                >
                  All (open + resolved)
                </Button>
                <Button
                  variant={resolutionFilter === 'open' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setResolutionFilter('open')}
                >
                  Open only
                </Button>
                <Button
                  variant={resolutionFilter === 'resolved' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setResolutionFilter('resolved')}
                >
                  Resolved only
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

              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="alert-device-filter">Device filter</Label>
                  <Input
                    id="alert-device-filter"
                    value={deviceFilterRaw}
                    onChange={(e) => setDeviceFilterRaw(e.target.value)}
                    placeholder="device id (exact match)"
                  />
                </div>
                <div className="space-y-1">
                  <Label>Type filter</Label>
                  <div className="flex flex-wrap gap-2">
                    <Button variant={typeFilter === 'all' ? 'default' : 'outline'} size="sm" onClick={() => setTypeFilter('all')}>
                      All types
                    </Button>
                    {typeOptions.map((t) => (
                      <Button key={t} variant={typeFilter === t ? 'default' : 'outline'} size="sm" onClick={() => setTypeFilter(t)}>
                        {fmtAlertType(t)}
                      </Button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {q.isLoading ? <div className="text-sm text-muted-foreground">Loading...</div> : null}
            {q.isError ? <div className="text-sm text-destructive">Error: {(q.error as Error).message}</div> : null}
            <DataTable<AlertOut>
              data={filtered}
              columns={cols}
              enableSorting
              initialSorting={[{ id: 'created_at', desc: true }]}
              emptyState="No alerts match your filters."
            />

            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              <div className="text-xs text-muted-foreground">{q.hasNextPage ? 'More available...' : 'End of feed.'}</div>
              <Button variant="outline" size="sm" disabled={!q.hasNextPage || q.isFetchingNextPage} onClick={() => q.fetchNextPage()}>
                {q.isFetchingNextPage ? 'Loading...' : 'Load more'}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}
