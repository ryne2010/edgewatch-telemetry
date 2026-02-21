import React from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link } from '@tanstack/react-router'
import { useDebouncedValue } from '@tanstack/react-pacer/debouncer'
import { useAppSettings } from '../app/settings'
import { api, type AlertOut, type NotificationEventOut } from '../api'
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
import { fmtAlertType, fmtDateTime, timeAgo } from '../utils/format'

type SeverityFilter = 'all' | 'critical' | 'warning' | 'info'
type SeverityKind = Exclude<SeverityFilter, 'all'>

type TimelineGroup = {
  dayKey: string
  dayLabel: string
  rows: AlertOut[]
  totals: {
    total: number
    critical: number
    warning: number
    info: number
  }
}

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

function buildTimelineGroups(rows: AlertOut[], maxGroups = 7): TimelineGroup[] {
  const sorted = [...rows].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
  const map = new Map<string, TimelineGroup>()

  for (const row of sorted) {
    const created = new Date(row.created_at)
    if (!Number.isFinite(created.getTime())) continue
    const dayKey = created.toISOString().slice(0, 10)
    const dayLabel = created.toLocaleDateString(undefined, {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
    const kind = sevKind(row.severity)

    let g = map.get(dayKey)
    if (!g) {
      g = {
        dayKey,
        dayLabel,
        rows: [],
        totals: { total: 0, critical: 0, warning: 0, info: 0 },
      }
      map.set(dayKey, g)
    }
    g.rows.push(row)
    g.totals.total += 1
    g.totals[kind] += 1
  }

  return Array.from(map.values()).slice(0, maxGroups)
}

export function AlertsPage() {
  const { adminKey } = useAppSettings()

  const healthQ = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })

  const adminEnabled = Boolean(healthQ.data?.features?.admin?.enabled)
  const adminAuthMode = String(healthQ.data?.features?.admin?.auth_mode ?? 'key').toLowerCase()
  const adminAccess = adminEnabled && (adminAuthMode === 'none' || Boolean(adminKey))
  const adminCred = adminAuthMode === 'key' ? (adminKey ?? '') : ''

  const [limit, setLimit] = React.useState(200)
  const [openOnly, setOpenOnly] = React.useState(false)
  const [severity, setSeverity] = React.useState<SeverityFilter>('all')
  const [typeFilter, setTypeFilter] = React.useState('all')
  const [deviceFilterRaw, setDeviceFilterRaw] = React.useState('')
  const [deviceFilter] = useDebouncedValue(deviceFilterRaw, { wait: 250 })
  const [searchRaw, setSearchRaw] = React.useState('')
  const [search] = useDebouncedValue(searchRaw, { wait: 200 })

  type Cursor = { before: string; before_id: string }

  const q = useInfiniteQuery({
    queryKey: ['alerts', { pageSize: limit, openOnly, severity, typeFilter, deviceFilter }],
    initialPageParam: undefined as Cursor | undefined,
    queryFn: ({ pageParam }) =>
      api.alerts({
        limit,
        open_only: openOnly,
        severity: severity === 'all' ? undefined : severity,
        alert_type: typeFilter === 'all' ? undefined : typeFilter,
        device_id: deviceFilter.trim() || undefined,
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
    const s = search.trim().toLowerCase()
    return rows.filter((a) => {
      if (!s) return true
      return `${a.device_id} ${a.alert_type} ${a.message}`.toLowerCase().includes(s)
    })
  }, [rows, search])

  const openCount = React.useMemo(() => filtered.filter((r) => !r.resolved_at).length, [filtered])
  const resolvedCount = filtered.length - openCount

  const volume = React.useMemo(() => buildVolumeSeries(filtered, { hours: 7 * 24 }), [filtered])
  const timelineGroups = React.useMemo(() => buildTimelineGroups(filtered, 7), [filtered])

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

  const routedEventsForShown = React.useMemo(() => {
    const out: NotificationEventOut[] = []
    for (const row of filtered) {
      const n = notificationByAlertId.get(row.id)
      if (n) out.push(n)
    }
    return out
  }, [filtered, notificationByAlertId])

  const routingDecisionCounts = React.useMemo(() => {
    const counts = new Map<string, number>()
    for (const n of routedEventsForShown) {
      const key = (n.decision || '').trim() || 'unknown'
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])
  }, [routedEventsForShown])

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
      description="Timeline-grouped alert feed with device/type/severity filters and routing-audit visibility."
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
        <Card>
          <CardHeader>
            <CardTitle>Total</CardTitle>
            <CardDescription>Shown rows</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{filtered.length}</div>
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

      <Card>
        <CardHeader>
          <CardTitle>Timeline</CardTitle>
          <CardDescription>Alerts grouped by day so spikes and incident windows are easier to scan.</CardDescription>
        </CardHeader>
        <CardContent>
          {timelineGroups.length === 0 ? (
            <div className="text-sm text-muted-foreground">No timeline groups for current filters.</div>
          ) : (
            <div className="space-y-3">
              {timelineGroups.map((g) => (
                <div key={g.dayKey} className="rounded-lg border bg-background p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="text-sm font-semibold">{g.dayLabel}</div>
                    <Badge variant="outline">total: {g.totals.total}</Badge>
                    <Badge variant="destructive">critical: {g.totals.critical}</Badge>
                    <Badge variant="warning">warning: {g.totals.warning}</Badge>
                    <Badge variant="secondary">info: {g.totals.info}</Badge>
                  </div>
                  <div className="mt-2 space-y-1">
                    {g.rows.slice(0, 4).map((r) => (
                      <div key={r.id} className="grid gap-1 text-xs sm:grid-cols-[7rem_12rem_1fr]">
                        <div className="font-mono text-muted-foreground">
                          {new Date(r.created_at).toLocaleTimeString(undefined, {
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit',
                            hour12: false,
                          })}
                        </div>
                        <div className="font-mono text-muted-foreground">{r.device_id}</div>
                        <div className="truncate text-muted-foreground">
                          {fmtAlertType(r.alert_type)} - {r.message}
                        </div>
                      </div>
                    ))}
                    {g.rows.length > 4 ? (
                      <div className="text-xs text-muted-foreground">+ {g.rows.length - 4} more</div>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Routing audit</CardTitle>
          <CardDescription>Dedupe/throttle/quiet-hours decision visibility for alerts in the current view.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {!adminEnabled ? (
            <div className="text-sm text-muted-foreground">
              Admin routes are disabled on this deployment, so notification routing audits are unavailable here.
            </div>
          ) : adminAuthMode === 'key' && !adminKey ? (
            <div className="text-sm text-muted-foreground">
              Configure an admin key in <Link to="/settings" className="underline">Settings</Link> to load routing decisions.
            </div>
          ) : (
            <>
              {notificationsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading routing events...</div> : null}
              {notificationsQ.isError ? (
                <div className="text-sm text-destructive">Routing audit error: {(notificationsQ.error as Error).message}</div>
              ) : null}
              {!notificationsQ.isLoading && !notificationsQ.isError ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">matched events: {routedEventsForShown.length}</Badge>
                    {routingDecisionCounts.map(([decision, count]) => (
                      <Badge key={decision} variant="secondary">
                        {decision}: {count}
                      </Badge>
                    ))}
                  </div>
                  {routedEventsForShown.length === 0 ? (
                    <div className="text-sm text-muted-foreground">
                      No routing decisions matched the currently shown alerts (or those events are outside the loaded audit window).
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {routedEventsForShown.slice(0, 6).map((n) => (
                        <div key={n.id} className="rounded-md border bg-background p-2 text-xs">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant={routingVariant(n.decision, n.delivered)}>{n.decision}</Badge>
                            <span className="font-mono text-muted-foreground">{n.device_id}</span>
                            <span className="text-muted-foreground">{fmtDateTime(n.created_at)}</span>
                          </div>
                          <div className="mt-1 text-muted-foreground">{n.reason}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Feed</CardTitle>
          <CardDescription>Use filters to focus on active devices and relevant alert types.</CardDescription>
          <div className="mt-3 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
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
    </Page>
  )
}
