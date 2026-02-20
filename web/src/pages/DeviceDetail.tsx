import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from '@tanstack/react-router'
import { api, type TimeseriesMultiPoint } from '../api'
import { LineChart, type Point } from '../ui/LineChart'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Label, Page } from '../portfolio-ui'

const METRIC_OPTIONS = [
  { value: 'water_pressure_psi', label: 'water_pressure_psi' },
  { value: 'oil_pressure_psi', label: 'oil_pressure_psi' },
  { value: 'battery_v', label: 'battery_v' },
] as const

type MetricKey = (typeof METRIC_OPTIONS)[number]['value']
type Bucket = 'minute' | 'hour'

function toSeriesByMetric(rows: TimeseriesMultiPoint[], metrics: readonly string[]): Record<string, Point[]> {
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

// Tiny local select to avoid extra UI deps.
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

export function DeviceDetailPage() {
  const { deviceId } = useParams({ from: '/devices/$deviceId' })

  const deviceQ = useQuery({
    queryKey: ['device', deviceId],
    queryFn: () => api.device(deviceId),
  })

  // Local state is the simplest, most reliable way to ensure metric switching is instant.
  const [metric, setMetric] = React.useState<MetricKey>('water_pressure_psi')
  const [bucket, setBucket] = React.useState<Bucket>('minute')

  const metricLabel = React.useMemo(() => {
    if (metric === 'water_pressure_psi') return 'Water pressure (psi)'
    if (metric === 'oil_pressure_psi') return 'Oil pressure (psi)'
    if (metric === 'battery_v') return 'Battery (V)'
    return metric
  }, [metric])

  const yAxisLabel = React.useMemo(() => {
    if (metric.endsWith('_psi')) return `${metric} (psi)`
    if (metric.endsWith('_v')) return `${metric} (V)`
    return metric
  }, [metric])

  const seriesOpts = React.useMemo(() => {
    const now = Date.now()
    const rangeMs = bucket === 'minute' ? 6 * 60 * 60 * 1000 : 7 * 24 * 60 * 60 * 1000
    const limit = bucket === 'minute' ? 360 : 168
    return { since: new Date(now - rangeMs).toISOString(), limit }
  }, [bucket])

  const metrics = React.useMemo(() => METRIC_OPTIONS.map((m) => m.value), [])

  // Fetch all chart metrics in a single request so switching is instantaneous.
  const seriesMultiQ = useQuery({
    queryKey: ['timeseries_multi', deviceId, bucket],
    queryFn: () => api.timeseriesMulti(deviceId, [...metrics], bucket, seriesOpts),
    select: (rows) => toSeriesByMetric(rows, metrics),
    staleTime: 60_000,
    refetchInterval: 15_000,
    refetchOnWindowFocus: false,
  })

  const latestQ = useQuery({
    queryKey: ['latestTelemetry', deviceId],
    queryFn: () => api.latestTelemetry(deviceId),
    refetchInterval: 10_000,
  })

  const points = seriesMultiQ.data?.[metric] ?? []
  const chartsLoading = seriesMultiQ.isLoading

  return (
    <Page
      title="Device detail"
      description={
        <span>
          Device: <span className="font-mono text-xs">{deviceId}</span>
        </span>
      }
    >
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Status</CardTitle>
            <CardDescription>Heartbeat-derived status and thresholds.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {deviceQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
            {deviceQ.isError ? <div className="text-sm text-destructive">Error: {(deviceQ.error as Error).message}</div> : null}
            {deviceQ.data ? (
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Status</span>
                  <Badge
                    variant={
                      deviceQ.data.status === 'online'
                        ? 'success'
                        : deviceQ.data.status === 'offline'
                          ? 'destructive'
                          : 'secondary'
                    }
                  >
                    {deviceQ.data.status}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Last seen</span>
                  <span>{deviceQ.data.last_seen_at ? new Date(deviceQ.data.last_seen_at).toLocaleString() : '—'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Heartbeat interval (s)</span>
                  <span className="font-mono text-xs">{deviceQ.data.heartbeat_interval_s}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Offline after (s)</span>
                  <span className="font-mono text-xs">{deviceQ.data.offline_after_s}</span>
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
                    <span className="font-mono text-xs">{new Date(latestQ.data.ts).toLocaleString()}</span>
                  </div>
                  {(['water_pressure_psi', 'oil_pressure_psi', 'battery_v', 'signal_rssi', 'pump_on'] as const).map((k) => (
                    <div key={k} className="flex items-center justify-between">
                      <span className="text-muted-foreground">{k}</span>
                      <span className="font-mono text-xs">{String((latestQ.data.metrics as any)?.[k] ?? '—')}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Telemetry</CardTitle>
            <CardDescription>Select metric + bucket and view a tiny local SVG chart (no CDNs).</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>Metric</Label>
                <SmallSelect
                  value={metric}
                  onChange={(v) => setMetric(v as MetricKey)}
                  options={METRIC_OPTIONS as any}
                  disabled={chartsLoading}
                />
              </div>

              <div className="space-y-2">
                <Label>Bucket</Label>
                <SmallSelect
                  value={bucket}
                  onChange={(v) => setBucket(v as Bucket)}
                  options={[
                    { value: 'minute', label: 'minute' },
                    { value: 'hour', label: 'hour' },
                  ]}
                  disabled={chartsLoading}
                />
              </div>
            </div>

            {seriesMultiQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
            {seriesMultiQ.isError ? (
              <div className="text-sm text-destructive">Error: {(seriesMultiQ.error as Error).message}</div>
            ) : null}

            <div className="relative rounded-md border bg-muted/30 p-3">
              {seriesMultiQ.isFetching || seriesMultiQ.isLoading ? (
                <div className="absolute right-3 top-3 z-10 rounded-md border bg-background/80 px-2 py-1 text-xs text-muted-foreground backdrop-blur">
                  Updating…
                </div>
              ) : null}
              <LineChart points={points} height={240} title={metricLabel} yAxisLabel={yAxisLabel} />
            </div>

            <div className="text-xs text-muted-foreground">
              Auto-refresh every 15s. Showing last {bucket === 'minute' ? '6 hours' : '7 days'}.
              {seriesMultiQ.dataUpdatedAt ? ` Updated: ${new Date(seriesMultiQ.dataUpdatedAt).toLocaleTimeString()}.` : null}
            </div>
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}
