import React from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link, useParams } from '@tanstack/react-router'
import { api, type DriftEventOut, type IngestionBatchOut, type NotificationEventOut, type TelemetryContract, type TelemetryPoint, type TimeseriesMultiPoint } from '../api'
import { LineChart, type Point } from '../ui/LineChart'
import { Sparkline } from '../ui/Sparkline'
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
} from '../ui-kit'
import { useAppSettings } from '../app/settings'
import { fmtDateTime, fmtNumber } from '../utils/format'

type Bucket = 'minute' | 'hour'
type TabKey = 'overview' | 'telemetry' | 'ingestions' | 'drift' | 'notifications' | 'cameras'

function statusVariant(status: 'online' | 'offline' | 'unknown'): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (status === 'online') return 'success'
  if (status === 'offline') return 'destructive'
  return 'secondary'
}

function toSeriesByMetric(rows: TimeseriesMultiPoint[], metrics: string[]): Record<string, Point[]> {
  const out: Record<string, Point[]> = Object.fromEntries(metrics.map((m) => [m, []]))
  for (const r of rows) {
    const x = Date.parse(r.bucket_ts)
    for (const m of metrics) {
      const v = r.values?.[m]
      if (typeof v === 'number' && Number.isFinite(v)) {
        out[m].push({ x, y: v })
      }
    }
  }
  return out
}

function metricLabel(contract: TelemetryContract | undefined, key: string): string {
  const unit = contract?.metrics?.[key]?.unit
  if (unit) return `${key} (${unit})`
  return key
}

function isNumericMetric(contract: TelemetryContract | undefined, key: string): boolean {
  const t = contract?.metrics?.[key]?.type
  return !t || t === 'number'
}

function formatMetricValue(key: string, value: unknown, contract?: TelemetryContract): string {
  const meta = contract?.metrics?.[key]
  if (meta?.type === 'boolean') {
    if (typeof value === 'boolean') return value ? 'true' : 'false'
    return '—'
  }
  if (meta?.type === 'string') {
    return typeof value === 'string' ? value : '—'
  }
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'

  const unit = meta?.unit ?? null
  if (unit === 'percent' || key.endsWith('_pct')) return `${fmtNumber(value, { digits: 2 })}%`
  if (unit === 'psi' || key.endsWith('_psi')) return `${fmtNumber(value, { digits: 2 })} psi`
  if (unit === 'volts' || key.endsWith('_v')) return `${fmtNumber(value, { digits: 2 })} V`
  if (unit === 'dBm' || key.endsWith('_dbm')) return `${fmtNumber(value, { digits: 0 })} dBm`
  if (unit === 'celsius' || key.endsWith('_c')) return `${fmtNumber(value, { digits: 2 })} °C`
  if (unit === 'gpm' || key.endsWith('_gpm')) return `${fmtNumber(value, { digits: 2 })} gpm`
  return fmtNumber(value, { digits: 2 })
}

function SmallSelect(props: {
  value: string
  onChange: (v: string) => void
  options: Array<{ value: string; label: string }>
  disabled?: boolean
}) {
  return (
    <select
      className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      value={props.value}
      disabled={props.disabled}
      onChange={(e) => props.onChange(e.target.value)}
    >
      {props.options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

function Callout(props: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-4">
      <div className="text-sm font-medium">{props.title}</div>
      <div className="mt-1 text-sm text-muted-foreground">{props.children}</div>
    </div>
  )
}

export function DeviceDetailPage() {
  const { deviceId } = useParams({ from: '/devices/$deviceId' })
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

  const [tab, setTab] = React.useState<TabKey>('overview')
  const [bucket, setBucket] = React.useState<Bucket>('minute')
  const [metric, setMetric] = React.useState<string>('water_pressure_psi')
  const [rawLimit, setRawLimit] = React.useState(100)
  const [rawSearch, setRawSearch] = React.useState('')

  const deviceQ = useQuery({ queryKey: ['device', deviceId], queryFn: () => api.device(deviceId), refetchInterval: 10_000 })
  const contractQ = useQuery({ queryKey: ['telemetryContract'], queryFn: api.telemetryContract, staleTime: 5 * 60_000 })
  const latestQ = useQuery({ queryKey: ['latestTelemetry', deviceId], queryFn: () => api.latestTelemetry(deviceId), refetchInterval: 10_000 })

  const contract = contractQ.data
  const metricKeys = React.useMemo(() => {
    const keys = Object.keys(contract?.metrics ?? {})
    keys.sort()
    return keys
  }, [contract])

  React.useEffect(() => {
    if (!metricKeys.length) return
    if (!metricKeys.includes(metric)) {
      // Prefer a familiar default if present.
      const fallback = metricKeys.includes('water_pressure_psi') ? 'water_pressure_psi' : metricKeys[0]
      setMetric(fallback)
    }
  }, [metricKeys, metric])

  const sparkMetrics = React.useMemo(() => {
    const base = [
      'water_pressure_psi',
      'oil_pressure_psi',
      'temperature_c',
      'humidity_pct',
      'battery_v',
      'signal_rssi_dbm',
    ]
    return base
      .filter((k) => (contract ? Boolean(contract.metrics[k]) : true))
      .filter((k) => isNumericMetric(contract, k))
  }, [contract])

  const chartMetrics = React.useMemo(() => {
    const out: string[] = []
    const add = (k: string) => {
      if (!k) return
      if (out.includes(k)) return
      if (out.length >= 10) return
      out.push(k)
    }

    // Start with the most important vitals (stable order).
    for (const k of sparkMetrics) add(k)

    // Fill remaining slots with other numeric metrics (stable order).
    for (const k of metricKeys) {
      if (out.length >= 10) break
      if (!isNumericMetric(contract, k)) continue
      add(k)
    }

    // Ensure the currently-selected metric is included.
    // If it isn't present already, put it first so the Quick chart stays snappy.
    if (isNumericMetric(contract, metric) && !out.includes(metric)) {
      out.unshift(metric)
    }

    // Enforce max size after the potential unshift.
    const trimmed = out.slice(0, 10)

    // Safety fallback
    if (!trimmed.length) {
      return ['water_pressure_psi']
    }

    return trimmed
  }, [contract, metric, sparkMetrics, metricKeys])

  const metricIsNumeric = isNumericMetric(contract, metric)

  const seriesOpts = React.useMemo(() => {
    const now = Date.now()
    const rangeMs = bucket === 'minute' ? 6 * 60 * 60 * 1000 : 7 * 24 * 60 * 60 * 1000
    const limit = bucket === 'minute' ? 360 : 168
    return { since: new Date(now - rangeMs).toISOString(), limit }
  }, [bucket])

  const seriesMultiQ = useQuery({
    queryKey: ['timeseries_multi', deviceId, bucket, contract?.sha256, chartMetrics.join('|')],
    queryFn: () => api.timeseriesMulti(deviceId, chartMetrics.length ? chartMetrics : ['water_pressure_psi'], bucket, seriesOpts),
    select: (rows) => toSeriesByMetric(rows, chartMetrics.length ? chartMetrics : ['water_pressure_psi']),
    staleTime: 60_000,
    refetchInterval: 15_000,
    refetchOnWindowFocus: false,
    enabled: Boolean(deviceId) && chartMetrics.length > 0,
  })

  const chartPoints = metricIsNumeric ? seriesMultiQ.data?.[metric] ?? [] : []

  // Raw points for debugging.
  const rawQ = useQuery({
    queryKey: ['telemetry_raw', deviceId, metric, rawLimit],
    queryFn: () => api.telemetry(deviceId, { metric, limit: rawLimit }),
    staleTime: 10_000,
    enabled: tab === 'telemetry',
  })

  // Admin lanes (audit trails).
  const ingestionsQ = useQuery({
    queryKey: ['admin', 'ingestions', deviceId],
    queryFn: () => api.admin.ingestions(adminCred, { device_id: deviceId, limit: 200 }),
    enabled: tab === 'ingestions' && adminAccess,
  })
  const driftQ = useQuery({
    queryKey: ['admin', 'drift', deviceId],
    queryFn: () => api.admin.driftEvents(adminCred, { device_id: deviceId, limit: 200 }),
    enabled: tab === 'drift' && adminAccess,
  })
  const notificationsQ = useQuery({
    queryKey: ['admin', 'notifications', deviceId],
    queryFn: () => api.admin.notifications(adminCred, { device_id: deviceId, limit: 200 }),
    enabled: tab === 'notifications' && adminAccess,
  })

  const latestMetrics = latestQ.data?.metrics ?? null

  const pinned = React.useMemo(() => {
    // Curated operational set.
    return [
      'water_pressure_psi',
      'oil_pressure_psi',
      'temperature_c',
      'humidity_pct',
      'oil_level_pct',
      'oil_life_pct',
      'drip_oil_level_pct',
      'battery_v',
      'signal_rssi_dbm',
      'pump_on',
      'flow_rate_gpm',
      'device_state',
    ].filter((k) => (contract ? Boolean(contract.metrics[k]) : true))
  }, [contract])

  const tabs: Array<{ key: TabKey; label: string; requiresAdminRoutes?: boolean }> = [
    { key: 'overview', label: 'Overview' },
    { key: 'telemetry', label: 'Telemetry' },
    { key: 'ingestions', label: 'Ingestions', requiresAdminRoutes: true },
    { key: 'drift', label: 'Drift', requiresAdminRoutes: true },
    { key: 'notifications', label: 'Notifications', requiresAdminRoutes: true },
    { key: 'cameras', label: 'Cameras' },
  ]

  const visibleTabs = tabs.filter((t) => !t.requiresAdminRoutes || adminEnabled)

  React.useEffect(() => {
    // Avoid clobbering deep links until we know whether the backend enabled admin routes.
    if (!healthQ.isSuccess) return
    if (adminEnabled) return
    if (tab === 'ingestions' || tab === 'drift' || tab === 'notifications') {
      setTab('overview')
    }
  }, [healthQ.isSuccess, adminEnabled, tab])

  const tabButtons = (
    <div className="flex flex-wrap items-center gap-2">
      {visibleTabs.map((t) => (
        <Button
          key={t.key}
          size="sm"
          variant={tab === t.key ? 'default' : 'outline'}
          onClick={() => setTab(t.key)}
        >
          {t.label}
        </Button>
      ))}
      {!adminEnabled ? (
        <Badge variant="outline" className="ml-auto">
          Admin routes disabled
        </Badge>
      ) : adminAuthMode === 'none' ? (
        <Badge variant="outline" className="ml-auto">
          Admin (IAM)
        </Badge>
      ) : adminKey ? (
        <Badge variant="outline" className="ml-auto">
          Admin (key)
        </Badge>
      ) : (
        <Badge variant="outline" className="ml-auto">
          Admin key needed
        </Badge>
      )}
    </div>
  )

  // --- Tables for admin tabs ---
  const ingestionCols = React.useMemo<ColumnDef<IngestionBatchOut>[]>(() => {
    return [
      { header: 'Received', accessorKey: 'received_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as any)}</span> },
      { header: 'Status', accessorKey: 'processing_status', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
      { header: 'Accepted', accessorKey: 'points_accepted', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Dupes', accessorKey: 'duplicates', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Quarantine', accessorKey: 'points_quarantined', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Unknown keys', cell: (i) => <span className="font-mono text-xs">{(i.row.original.unknown_metric_keys ?? []).length}</span> },
      { header: 'Type mismatches', cell: (i) => <span className="font-mono text-xs">{(i.row.original.type_mismatch_keys ?? []).length}</span> },
      { header: 'Contract', cell: (i) => <span className="font-mono text-xs">{i.row.original.contract_version}</span> },
    ]
  }, [])

  const driftCols = React.useMemo<ColumnDef<DriftEventOut>[]>(() => {
    return [
      { header: 'Created', accessorKey: 'created_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as any)}</span> },
      { header: 'Type', accessorKey: 'event_type' },
      { header: 'Action', accessorKey: 'action', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
      { header: 'Batch', accessorKey: 'batch_id', cell: (i) => <span className="font-mono text-xs">{String(i.getValue()).slice(0, 8)}…</span> },
      {
        header: 'Details',
        cell: (i) => (
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">view</summary>
            <pre className="mt-2 whitespace-pre-wrap break-words">{JSON.stringify(i.row.original.details, null, 2)}</pre>
          </details>
        ),
      },
    ]
  }, [])

  const notificationCols = React.useMemo<ColumnDef<NotificationEventOut>[]>(() => {
    return [
      { header: 'Created', accessorKey: 'created_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as any)}</span> },
      { header: 'Type', accessorKey: 'alert_type' },
      { header: 'Channel', accessorKey: 'channel', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
      { header: 'Decision', accessorKey: 'decision' },
      { header: 'Delivered', accessorKey: 'delivered', cell: (i) => (i.getValue() ? <Badge variant="success">yes</Badge> : <Badge variant="destructive">no</Badge>) },
      { header: 'Reason', accessorKey: 'reason', cell: (i) => <span className="text-muted-foreground">{String(i.getValue())}</span> },
    ]
  }, [])

  const rawCols = React.useMemo<ColumnDef<TelemetryPoint>[]>(() => {
    return [
      { header: 'Timestamp', accessorKey: 'ts', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as any)}</span> },
      { header: 'Message', accessorKey: 'message_id', cell: (i) => <span className="font-mono text-xs">{String(i.getValue()).slice(0, 12)}…</span> },
      {
        header: 'Value',
        cell: (i) => {
          const v = (i.row.original.metrics as any)?.[metric]
          return <span className="font-mono text-xs">{formatMetricValue(metric, v, contract)}</span>
        },
      },
      {
        header: 'Metrics',
        cell: (i) => (
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">view</summary>
            <pre className="mt-2 whitespace-pre-wrap break-words">{JSON.stringify(i.row.original.metrics, null, 2)}</pre>
          </details>
        ),
      },
    ]
  }, [metric, contract])

  const rawFiltered = React.useMemo(() => {
    const s = rawSearch.trim().toLowerCase()
    const rows = rawQ.data ?? []
    if (!s) return rows
    return rows.filter((r) => JSON.stringify(r.metrics).toLowerCase().includes(s))
  }, [rawQ.data, rawSearch])

  const timeFormatter = React.useCallback(
    (ms: number) => {
      const d = new Date(ms)
      return bucket === 'minute'
        ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : d.toLocaleDateString()
    },
    [bucket],
  )

  return (
    <Page
      title="Device"
      description={
        <span>
          <span className="text-muted-foreground">Device</span>{' '}
          <span className="font-mono text-xs">{deviceId}</span>
        </span>
      }
      actions={tabButtons}
    >
      {deviceQ.isError ? <div className="text-sm text-destructive">Error: {(deviceQ.error as Error).message}</div> : null}
      {deviceQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}

      {tab === 'overview' ? (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Status</CardTitle>
                <CardDescription>Heartbeat-derived status and thresholds.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {deviceQ.data ? (
                  <div className="space-y-2 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Status</span>
                      <Badge variant={statusVariant(deviceQ.data.status)}>{deviceQ.data.status}</Badge>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Last seen</span>
                      <span>{fmtDateTime(deviceQ.data.last_seen_at)}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Heartbeat interval</span>
                      <span className="font-mono text-xs">{deviceQ.data.heartbeat_interval_s}s</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Offline after</span>
                      <span className="font-mono text-xs">{deviceQ.data.offline_after_s}s</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Enabled</span>
                      {deviceQ.data.enabled ? <Badge variant="success">enabled</Badge> : <Badge variant="secondary">disabled</Badge>}
                    </div>
                  </div>
                ) : null}

                <div className="pt-2">
                  <div className="text-sm font-medium">Latest telemetry</div>
                  {latestQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
                  {latestQ.isError ? <div className="text-sm text-destructive">Error: {(latestQ.error as Error).message}</div> : null}
                  {!latestQ.isLoading && !latestQ.isError && !latestQ.data ? (
                    <div className="text-sm text-muted-foreground">No telemetry points yet.</div>
                  ) : null}
                  {latestQ.data ? (
                    <div className="mt-2 space-y-1 text-sm">
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">Timestamp</span>
                        <span className="font-mono text-xs">{fmtDateTime(latestQ.data.ts)}</span>
                      </div>
                      {pinned.map((k) => (
                        <div key={k} className="flex items-center justify-between">
                          <span className="text-muted-foreground">{k}</span>
                          <span className="font-mono text-xs">
                            {formatMetricValue(k, (latestMetrics as any)?.[k], contract)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Quick chart</CardTitle>
                <CardDescription>Hover for a tooltip. Common metrics are cached (max 10) for snappy switching.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label>Metric</Label>
                    <SmallSelect
                      value={metric}
                      onChange={setMetric}
                      options={metricKeys.map((k) => ({ value: k, label: metricLabel(contract, k) }))}
                      disabled={seriesMultiQ.isLoading}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Bucket</Label>
                    <SmallSelect
                      value={bucket}
                      onChange={(v) => setBucket(v as Bucket)}
                      options={[
                        { value: 'minute', label: 'minute (last 6h)' },
                        { value: 'hour', label: 'hour (last 7d)' },
                      ]}
                      disabled={seriesMultiQ.isLoading}
                    />
                  </div>
                </div>

                {seriesMultiQ.isError ? (
                  <div className="text-sm text-destructive">Error: {(seriesMultiQ.error as Error).message}</div>
                ) : null}

                {!metricIsNumeric ? (
                  <Callout title="Not chartable">
                    Charts are available for numeric metrics only. Use the Telemetry tab (raw points) to inspect booleans/strings.
                  </Callout>
                ) : null}

                <div className="relative rounded-md border bg-muted/30 p-3">
                  {seriesMultiQ.isFetching || seriesMultiQ.isLoading ? (
                    <div className="absolute right-3 top-3 z-10 rounded-md border bg-background/80 px-2 py-1 text-xs text-muted-foreground backdrop-blur">
                      Updating…
                    </div>
                  ) : null}
                  {metricIsNumeric ? (
                    <LineChart
                      points={chartPoints}
                      height={240}
                      title={metricLabel(contract, metric)}
                      yAxisLabel={metricLabel(contract, metric)}
                      valueFormatter={(v) => formatMetricValue(metric, v, contract)}
                      timeFormatter={timeFormatter}
                    />
                  ) : (
                    <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
                      Select a numeric metric to view a chart.
                    </div>
                  )}
                </div>

                <div className="text-xs text-muted-foreground">
                  Auto-refresh every 15s. Showing last {bucket === 'minute' ? '6 hours' : '7 days'}.{' '}
                  {seriesMultiQ.dataUpdatedAt ? `Updated: ${new Date(seriesMultiQ.dataUpdatedAt).toLocaleTimeString()}.` : null}
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Vitals over time</CardTitle>
              <CardDescription>Small multiples for high-signal metrics (same cached multi-metric query).</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {seriesMultiQ.isError ? (
                <div className="text-sm text-destructive">Error: {(seriesMultiQ.error as Error).message}</div>
              ) : null}

              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {sparkMetrics.map((k) => (
                  <div key={k} className="rounded-lg border bg-background p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">{metricLabel(contract, k)}</div>
                        <div className="truncate text-xs text-muted-foreground">
                          {contract?.metrics?.[k]?.description ?? '—'}
                        </div>
                      </div>
                      <div className="shrink-0 font-mono text-xs">{formatMetricValue(k, (latestMetrics as any)?.[k], contract)}</div>
                    </div>
                    <div className="mt-2 text-primary">
                      <Sparkline points={seriesMultiQ.data?.[k] ?? []} height={64} ariaLabel={`${k} sparkline`} />
                    </div>
                  </div>
                ))}
              </div>

              <div className="text-xs text-muted-foreground">
                Sparklines use the same server-side bucket aggregation as the Quick chart.
              </div>
            </CardContent>
          </Card>

          {!contractQ.isLoading && contract ? (
            <Callout title="Telemetry contract">
              UI options are driven by <code className="font-mono">/api/v1/contracts/telemetry</code>. Version{' '}
              <span className="font-mono">{contract.version}</span> ({contract.sha256.slice(0, 12)}…).
            </Callout>
          ) : null}
        </div>
      ) : null}

      {tab === 'telemetry' ? (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Telemetry</CardTitle>
              <CardDescription>
                Metric-driven charting + raw point explorer. Use this when debugging drift or sensor anomalies.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 lg:grid-cols-3">
                <div className="space-y-2 lg:col-span-1">
                  <Label>Metric</Label>
                  <SmallSelect
                    value={metric}
                    onChange={setMetric}
                    options={metricKeys.map((k) => ({ value: k, label: metricLabel(contract, k) }))}
                    disabled={seriesMultiQ.isLoading}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Bucket</Label>
                  <SmallSelect
                    value={bucket}
                    onChange={(v) => setBucket(v as Bucket)}
                    options={[
                      { value: 'minute', label: 'minute (last 6h)' },
                      { value: 'hour', label: 'hour (last 7d)' },
                    ]}
                    disabled={seriesMultiQ.isLoading}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Raw rows</Label>
                  <Input
                    type="number"
                    min={10}
                    max={500}
                    value={rawLimit}
                    onChange={(e) => setRawLimit(Math.max(10, Math.min(500, Number(e.target.value) || 100)))}
                  />
                </div>
              </div>

              <div className="relative rounded-md border bg-muted/30 p-3">
                {seriesMultiQ.isFetching || seriesMultiQ.isLoading ? (
                  <div className="absolute right-3 top-3 z-10 rounded-md border bg-background/80 px-2 py-1 text-xs text-muted-foreground backdrop-blur">
                    Updating…
                  </div>
                ) : null}
                <LineChart
                  points={chartPoints}
                  height={260}
                  title={metricLabel(contract, metric)}
                  yAxisLabel={metricLabel(contract, metric)}
                  valueFormatter={(v) => formatMetricValue(metric, v, contract)}
                  timeFormatter={timeFormatter}
                />
              </div>

              <div className="grid gap-4 lg:grid-cols-3">
                <div className="lg:col-span-2">
                  <div className="flex items-end justify-between gap-2">
                    <div>
                      <div className="text-sm font-medium">Raw points</div>
                      <div className="text-xs text-muted-foreground">Latest points containing this metric.</div>
                    </div>
                    <div className="w-72">
                      <Input value={rawSearch} onChange={(e) => setRawSearch(e.target.value)} placeholder="Search JSON…" />
                    </div>
                  </div>
                  <div className="mt-3">
                    {rawQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
                    {rawQ.isError ? <div className="text-sm text-destructive">Error: {(rawQ.error as Error).message}</div> : null}
                    <DataTable<TelemetryPoint>
                      data={rawFiltered}
                      columns={rawCols}
                      height={420}
                      enableSorting
                      initialSorting={[{ id: 'ts', desc: true }]}
                      emptyState="No points for this metric yet."
                    />
                  </div>
                </div>

                <div className="space-y-4">
                  <Callout title="Tips">
                    <ul className="list-disc space-y-1 pl-5">
                      <li>Use <span className="font-mono">minute</span> for recent troubleshooting (faster signal).</li>
                      <li>Use <span className="font-mono">hour</span> for longer trends (stable view).</li>
                      <li>Unknown keys or type mismatches show up in the Admin &rarr; Drift tab.</li>
                    </ul>
                  </Callout>
                  <Callout title="Drift guardrails">
                    Contract enforcement is server-side. If a device begins sending breaking changes, points can be rejected
                    or quarantined depending on the configured mode.
                  </Callout>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}

      {tab === 'ingestions' ? (
        <div className="space-y-6">
          {adminAuthMode === 'key' && !adminKey ? (
            <Callout title="Admin key required">
              To view ingestion audit trails, configure an admin key in <Link to="/settings" className="underline">Settings</Link>.
            </Callout>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle>Ingestion batches</CardTitle>
              <CardDescription>Lineage + contract validation results per ingest request.</CardDescription>
            </CardHeader>
            <CardContent>
              {ingestionsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {ingestionsQ.isError ? <div className="text-sm text-destructive">Error: {(ingestionsQ.error as Error).message}</div> : null}
              <DataTable<IngestionBatchOut>
                data={ingestionsQ.data ?? []}
                columns={ingestionCols}
                height={520}
                enableSorting
                initialSorting={[{ id: 'received_at', desc: true }]}
                emptyState="No ingestion batches found."
              />
            </CardContent>
          </Card>
        </div>
      ) : null}

      {tab === 'drift' ? (
        <div className="space-y-6">
          {adminAuthMode === 'key' && !adminKey ? (
            <Callout title="Admin key required">
              To view drift events, configure an admin key in <Link to="/settings" className="underline">Settings</Link>.
            </Callout>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle>Drift events</CardTitle>
              <CardDescription>Contract drift detection (unknown keys + type mismatches).</CardDescription>
            </CardHeader>
            <CardContent>
              {driftQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {driftQ.isError ? <div className="text-sm text-destructive">Error: {(driftQ.error as Error).message}</div> : null}
              <DataTable<DriftEventOut>
                data={driftQ.data ?? []}
                columns={driftCols}
                height={520}
                enableSorting
                initialSorting={[{ id: 'created_at', desc: true }]}
                emptyState="No drift events found."
              />
            </CardContent>
          </Card>
        </div>
      ) : null}

      {tab === 'notifications' ? (
        <div className="space-y-6">
          {adminAuthMode === 'key' && !adminKey ? (
            <Callout title="Admin key required">
              To view notification audit trails, configure an admin key in{' '}
              <Link to="/settings" className="underline">Settings</Link>.
            </Callout>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle>Notifications</CardTitle>
              <CardDescription>Delivery attempts (dedupe, throttling, and quiet-hours decisions).</CardDescription>
            </CardHeader>
            <CardContent>
              {notificationsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {notificationsQ.isError ? <div className="text-sm text-destructive">Error: {(notificationsQ.error as Error).message}</div> : null}
              <DataTable<NotificationEventOut>
                data={notificationsQ.data ?? []}
                columns={notificationCols}
                height={520}
                enableSorting
                initialSorting={[{ id: 'created_at', desc: true }]}
                emptyState="No notification events found."
              />
            </CardContent>
          </Card>
        </div>
      ) : null}

      {tab === 'cameras' ? (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Cameras</CardTitle>
              <CardDescription>
                UI placeholder for the capture pipeline. Current scope: <strong>one camera active at a time</strong>.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Callout title="Planned features">
                <ul className="list-disc space-y-1 pl-5">
                  <li>Single active camera with a selector for up to 4 physical cameras.</li>
                  <li>Photo capture (on-demand + scheduled), plus short video clips.</li>
                  <li>Upload via cellular data SIM (bandwidth-aware, retry + backoff).</li>
                  <li>Retention and privacy posture documented per environment.</li>
                </ul>
              </Callout>

              <Callout title="Implementation status">
                The backend capture + media storage endpoints are intentionally left as a task queue item for @codex.
                See <code className="font-mono">docs/TASKS</code> and the camera runbook.
              </Callout>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </Page>
  )
}
