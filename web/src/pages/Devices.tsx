import React from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link } from '@tanstack/react-router'
import { api, type DeviceSummaryOut } from '../api'
import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, Input, Label, Page, Separator } from '../ui-kit'
import { fmtDateTime, fmtNumber, timeAgo } from '../utils/format'

function statusVariant(status: DeviceSummaryOut['status']): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (status === 'online') return 'success'
  if (status === 'offline') return 'destructive'
  return 'secondary'
}

function asNumber(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function MetricChip(props: { label: string; value: unknown; unit?: string; variant?: 'secondary' | 'warning' | 'destructive' }) {
  const v = props.value
  const text = typeof v === 'number' ? fmtNumber(v) : v == null ? '—' : String(v)
  const unit = props.unit ? ` ${props.unit}` : ''
  const variant = props.variant ?? 'secondary'
  return (
    <Badge variant={variant} className="font-mono text-[11px]">
      {props.label}: {text}
      {unit}
    </Badge>
  )
}

export function DevicesPage() {
  const edgePolicyQ = useQuery({ queryKey: ['edgePolicyContract'], queryFn: api.edgePolicyContract, staleTime: 5 * 60_000 })
  const devicesQ = useQuery({
    queryKey: ['devicesSummary', 'devicesPage'],
    queryFn: () =>
      api.devicesSummary({
        metrics: [
          'water_pressure_psi',
          'oil_pressure_psi',
          'oil_level_pct',
          'drip_oil_level_pct',
          'oil_life_pct',
          'temperature_c',
          'humidity_pct',
          'battery_v',
          'signal_rssi_dbm',
        ],
      }),
    refetchInterval: 10_000,
  })

  const [filterText, setFilterText] = React.useState('')
  const [statusFilter, setStatusFilter] = React.useState<DeviceSummaryOut['status'] | 'all'>('all')

  const devices = devicesQ.data ?? []

  const thresholds = edgePolicyQ.data?.alert_thresholds
  const wpLow = thresholds?.water_pressure_low_psi ?? 20
  const battLow = thresholds?.battery_low_v ?? 11.8
  const sigLow = thresholds?.signal_low_rssi_dbm ?? -95

  const oilPressureLow = thresholds?.oil_pressure_low_psi ?? 20
  const oilLevelLow = thresholds?.oil_level_low_pct ?? 20
  const dripOilLevelLow = thresholds?.drip_oil_level_low_pct ?? 20
  const oilLifeLow = thresholds?.oil_life_low_pct ?? 15

  const filtered = React.useMemo(() => {
    const q = filterText.trim().toLowerCase()
    return devices.filter((d) => {
      if (statusFilter !== 'all' && d.status !== statusFilter) return false
      if (!q) return true
      return d.device_id.toLowerCase().includes(q) || d.display_name.toLowerCase().includes(q)
    })
  }, [devices, filterText, statusFilter])

  const cols = React.useMemo<ColumnDef<DeviceSummaryOut>[]>(() => {
    return [
      {
        header: 'Status',
        accessorKey: 'status',
        cell: (info) => {
          const s = info.getValue() as DeviceSummaryOut['status']
          return <Badge variant={statusVariant(s)}>{s}</Badge>
        },
        size: 90,
      },
      {
        header: 'Device',
        accessorKey: 'device_id',
        cell: (info) => {
          const id = String(info.getValue())
          return (
            <Link to="/devices/$deviceId" params={{ deviceId: id }} className="font-mono text-xs underline">
              {id}
            </Link>
          )
        },
      },
      { header: 'Name', accessorKey: 'display_name' },
      {
        header: 'Vitals',
        id: 'vitals',
        cell: (info) => {
          const d = info.row.original
          const wp = asNumber(d.metrics?.water_pressure_psi)
          const oilP = asNumber(d.metrics?.oil_pressure_psi)
          const oilLvl = asNumber(d.metrics?.oil_level_pct)
          const drip = asNumber(d.metrics?.drip_oil_level_pct)
          const life = asNumber(d.metrics?.oil_life_pct)
          const batt = asNumber(d.metrics?.battery_v)
          const sig = asNumber(d.metrics?.signal_rssi_dbm)

          const wpVariant = wp != null && wp < wpLow ? 'destructive' : 'secondary'
          const oilPVariant = oilP != null && oilP < oilPressureLow ? 'destructive' : 'secondary'
          const oilLvlVariant = oilLvl != null && oilLvl < oilLevelLow ? 'warning' : 'secondary'
          const dripVariant = drip != null && drip < dripOilLevelLow ? 'warning' : 'secondary'
          const lifeVariant = life != null && life < oilLifeLow ? 'warning' : 'secondary'
          const battVariant = batt != null && batt < battLow ? 'destructive' : 'secondary'
          const sigVariant = sig != null && sig < sigLow ? 'warning' : 'secondary'

          return (
            <div className="flex flex-wrap gap-2">
              <MetricChip label="water" value={wp} unit="psi" variant={wpVariant} />
              <MetricChip label="oilP" value={oilP} unit="psi" variant={oilPVariant} />
              <MetricChip label="oilLvl" value={oilLvl} unit="%" variant={oilLvlVariant} />
              <MetricChip label="drip" value={drip} unit="%" variant={dripVariant} />
              <MetricChip label="life" value={life} unit="%" variant={lifeVariant} />
              <MetricChip label="temp" value={d.metrics?.temperature_c} unit="°C" />
              <MetricChip label="hum" value={d.metrics?.humidity_pct} unit="%" />
              <MetricChip label="batt" value={batt} unit="V" variant={battVariant} />
              <MetricChip label="rssi" value={sig} unit="dBm" variant={sigVariant} />
            </div>
          )
        },
      },
      {
        header: 'Last seen',
        accessorKey: 'last_seen_at',
        cell: (info) => {
          const ts = info.getValue() as string | null
          return (
            <div className="space-y-0.5">
              <div className="text-xs text-muted-foreground">{timeAgo(ts)}</div>
              <div className="text-[11px] text-muted-foreground">{fmtDateTime(ts)}</div>
            </div>
          )
        },
      },
    ]
  }, [wpLow, oilPressureLow, oilLevelLow, dripOilLevelLow, oilLifeLow, battLow, sigLow])

  const counts = React.useMemo(() => {
    const total = devices.length
    const online = devices.filter((d) => d.status === 'online').length
    const offline = devices.filter((d) => d.status === 'offline').length
    const unknown = devices.filter((d) => d.status === 'unknown').length
    return { total, online, offline, unknown }
  }, [devices])

  return (
    <Page
      title="Devices"
      description="Searchable fleet table (status + latest vitals)."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">total: {counts.total}</Badge>
          <Badge variant="success">online: {counts.online}</Badge>
          <Badge variant="destructive">offline: {counts.offline}</Badge>
          <Badge variant="secondary">unknown: {counts.unknown}</Badge>
          {devicesQ.isFetching ? <Badge variant="secondary">refreshing…</Badge> : null}
        </div>
      }
    >
      <Card>
        <CardHeader>
          <CardTitle>Fleet</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="search">Search</Label>
              <Input
                id="search"
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                placeholder="device id or name"
              />
              <div className="text-xs text-muted-foreground">Tip: paste a full device id to jump fast.</div>
            </div>

            <div className="space-y-2">
              <Label>Status</Label>
              <div className="flex flex-wrap gap-2">
                {(['all', 'online', 'offline', 'unknown'] as const).map((s) => (
                  <Badge
                    key={s}
                    variant={s === 'all' ? 'outline' : statusVariant(s as any)}
                    className={
                      'cursor-pointer select-none ' +
                      (statusFilter === s ? 'ring-2 ring-primary ring-offset-2 ring-offset-background' : '')
                    }
                    onClick={() => setStatusFilter(s as any)}
                  >
                    {s}
                  </Badge>
                ))}
              </div>
              <div className="text-xs text-muted-foreground">
                Thresholds: water &lt; {wpLow.toFixed(1)} psi, battery &lt; {battLow.toFixed(2)} V, rssi &lt; {sigLow} dBm
                {edgePolicyQ.isLoading ? ' (loading policy…)': ''}
              </div>
            </div>

            <div className="space-y-2">
              <Label>Policy</Label>
              <div className="text-xs text-muted-foreground">
                {edgePolicyQ.data ? (
                  <>
                    policy: <span className="font-mono">{edgePolicyQ.data.policy_version}</span> ·{' '}
                    <span className="font-mono">{edgePolicyQ.data.policy_sha256.slice(0, 10)}…</span>
                  </>
                ) : (
                  '—'
                )}
              </div>
              <Separator />
              <div className="text-xs text-muted-foreground">
                This page uses <code className="font-mono">/api/v1/devices/summary</code> to avoid N+1 calls.
              </div>
            </div>
          </div>

          {devicesQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
          {devicesQ.isError ? <div className="text-sm text-destructive">Error: {(devicesQ.error as Error).message}</div> : null}

          <DataTable<DeviceSummaryOut>
            data={filtered}
            columns={cols}
            height={560}
            enableSorting
            emptyState={filterText ? 'No devices match your search.' : 'No devices.'}
          />
        </CardContent>
      </Card>
    </Page>
  )
}
