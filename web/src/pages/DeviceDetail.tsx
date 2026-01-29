import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from '@tanstack/react-router'
import { useForm } from '@tanstack/react-form'
import { api } from '../api'
import { LineChart } from '../ui/LineChart'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Label, Page } from '../portfolio-ui'

function toChartPoints(rows: { bucket_ts: string; value: number }[]) {
  return rows.map((r) => ({ x: new Date(r.bucket_ts).getTime(), y: r.value }))
}

// Tiny local select to avoid extra UI deps.
function SmallSelect(props: {
  value: string
  onChange: (v: string) => void
  options: Array<{ value: string; label: string }>
}) {
  return (
    <select
      className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      value={props.value}
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

  const form = useForm({
    defaultValues: { metric: 'water_pressure_psi', bucket: 'minute' as 'minute' | 'hour' },
  })

  const metric = form.state.values.metric
  const bucket = form.state.values.bucket

  const seriesQ = useQuery({
    queryKey: ['timeseries', deviceId, metric, bucket],
    queryFn: () => api.timeseries(deviceId, metric, bucket),
    refetchInterval: 15_000,
  })

  const points = toChartPoints(seriesQ.data ?? [])

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
                  onChange={(v) => form.setFieldValue('metric', v)}
                  options={[
                    { value: 'water_pressure_psi', label: 'water_pressure_psi' },
                    { value: 'oil_pressure_psi', label: 'oil_pressure_psi' },
                    { value: 'battery_v', label: 'battery_v' },
                  ]}
                />
              </div>

              <div className="space-y-2">
                <Label>Bucket</Label>
                <SmallSelect
                  value={bucket}
                  onChange={(v) => form.setFieldValue('bucket', v as any)}
                  options={[
                    { value: 'minute', label: 'minute' },
                    { value: 'hour', label: 'hour' },
                  ]}
                />
              </div>
            </div>

            {seriesQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
            {seriesQ.isError ? <div className="text-sm text-destructive">Error: {(seriesQ.error as Error).message}</div> : null}

            <div className="rounded-md border bg-muted/30 p-3">
              <LineChart points={points} height={200} />
            </div>

            <div className="text-xs text-muted-foreground">Auto-refresh every 15s (configurable in the API).</div>
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}
