import React from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link, useLocation } from '@tanstack/react-router'
import { api, type DeviceSummaryOut } from '../api'
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, DataTable, Input, Label, Page } from '../ui-kit'
import { fmtDateTime, fmtNumber, timeAgo } from '../utils/format'

type DeviceStatusFilter = DeviceSummaryOut['status'] | 'all'

type ThresholdSnapshot = {
  wpLow: number
  battLow: number
  sigLow: number
}

type FleetHealth = {
  label: string
  detail: string
  variant: 'success' | 'warning' | 'destructive' | 'secondary'
}

function statusVariant(status: DeviceSummaryOut['status']): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (status === 'online') return 'success'
  if (status === 'offline') return 'destructive'
  return 'secondary'
}

function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.trunc(seconds))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  const remM = m % 60
  if (h < 24) return remM ? `${h}h ${remM}m` : `${h}h`
  const d = Math.floor(h / 24)
  const remH = h % 24
  return remH ? `${d}d ${remH}h` : `${d}d`
}

function asNumber(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function parseDevicesSearch(searchStr: string): {
  filterText: string
  statusFilter: DeviceStatusFilter
  openAlertsOnly: boolean
} {
  const params = new URLSearchParams(searchStr.startsWith('?') ? searchStr.slice(1) : searchStr)

  const rawStatus = String(params.get('status') ?? params.get('deviceStatus') ?? 'all').toLowerCase()
  const statusFilter: DeviceStatusFilter =
    rawStatus === 'online' || rawStatus === 'offline' || rawStatus === 'unknown' ? rawStatus : 'all'

  const filterText = String(params.get('q') ?? params.get('search') ?? '').trim()
  const rawOpen = String(params.get('openAlertsOnly') ?? params.get('open_alerts_only') ?? '').toLowerCase()
  const openAlertsOnly = rawOpen === '1' || rawOpen === 'true' || rawOpen === 'yes' || rawOpen === 'on'

  return { filterText, statusFilter, openAlertsOnly }
}

function computeFleetHealth(
  device: DeviceSummaryOut,
  thresholds: ThresholdSnapshot,
  hasOpenAlerts: boolean,
): FleetHealth {
  if (device.status === 'unknown') {
    return {
      label: 'awaiting telemetry',
      detail: 'No telemetry has been received yet. Verify device auth and run agent/simulate.',
      variant: 'secondary',
    }
  }

  const seconds = device.seconds_since_last_seen
  if (device.status === 'offline') {
    const offlineFor = seconds == null ? 'unknown' : fmtDuration(seconds)
    const overdue = seconds == null ? 'unknown' : fmtDuration(Math.max(0, seconds - device.offline_after_s))
    return {
      label: 'offline',
      detail: `Telemetry is stale (${offlineFor} since last seen; threshold ${fmtDuration(device.offline_after_s)}, overdue ${overdue}).`,
      variant: 'destructive',
    }
  }

  if (hasOpenAlerts) {
    return {
      label: 'open alerts',
      detail: 'Device is online but has unresolved alerts. Review Alerts for root cause and routing.',
      variant: 'warning',
    }
  }

  if (seconds != null && seconds > Math.max(device.heartbeat_interval_s * 2, 120)) {
    return {
      label: 'stale heartbeat',
      detail: `Last telemetry ${fmtDuration(seconds)} ago (heartbeat target ${fmtDuration(device.heartbeat_interval_s)}).`,
      variant: 'warning',
    }
  }

  const sig = asNumber(device.metrics?.signal_rssi_dbm)
  if (sig != null && sig < thresholds.sigLow) {
    return {
      label: 'weak signal',
      detail: `RSSI ${fmtNumber(sig)} dBm is below policy threshold (${thresholds.sigLow} dBm).`,
      variant: 'warning',
    }
  }

  const batt = asNumber(device.metrics?.battery_v)
  if (batt != null && batt < thresholds.battLow) {
    return {
      label: 'low battery',
      detail: `Battery ${fmtNumber(batt)} V is below policy threshold (${thresholds.battLow.toFixed(2)} V).`,
      variant: 'warning',
    }
  }

  const wp = asNumber(device.metrics?.water_pressure_psi)
  if (wp != null && wp < thresholds.wpLow) {
    return {
      label: 'water pressure low',
      detail: `Water pressure ${fmtNumber(wp)} psi is below policy threshold (${thresholds.wpLow.toFixed(1)} psi).`,
      variant: 'warning',
    }
  }

  return {
    label: 'healthy',
    detail: 'No stale telemetry, weak signal, low battery, or open-alert indicators.',
    variant: 'success',
  }
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
  const searchStr = useLocation({ select: (s) => s.searchStr })

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
  const openAlertsQ = useQuery({
    queryKey: ['alerts', 'open', 'devicesPage'],
    queryFn: () => api.alerts({ open_only: true, limit: 1000 }),
    refetchInterval: 15_000,
  })

  const initialSearchFilters = React.useMemo(() => parseDevicesSearch(searchStr), [searchStr])

  const [filterText, setFilterText] = React.useState(initialSearchFilters.filterText)
  const [statusFilter, setStatusFilter] = React.useState<DeviceStatusFilter>(initialSearchFilters.statusFilter)
  const [openAlertsOnly, setOpenAlertsOnly] = React.useState(initialSearchFilters.openAlertsOnly)

  React.useEffect(() => {
    const parsed = parseDevicesSearch(searchStr)
    setFilterText(parsed.filterText)
    setStatusFilter(parsed.statusFilter)
    setOpenAlertsOnly(parsed.openAlertsOnly)
  }, [searchStr])

  const devices = devicesQ.data ?? []
  const openAlertDeviceIds = React.useMemo(() => {
    return new Set((openAlertsQ.data ?? []).map((a) => a.device_id))
  }, [openAlertsQ.data])
  const openAlertsReady = openAlertsQ.isSuccess

  const thresholds = edgePolicyQ.data?.alert_thresholds
  const wpLow = thresholds?.water_pressure_low_psi ?? 20
  const battLow = thresholds?.battery_low_v ?? 11.8
  const sigLow = thresholds?.signal_low_rssi_dbm ?? -95

  const oilPressureLow = thresholds?.oil_pressure_low_psi ?? 20
  const oilLevelLow = thresholds?.oil_level_low_pct ?? 20
  const dripOilLevelLow = thresholds?.drip_oil_level_low_pct ?? 20
  const oilLifeLow = thresholds?.oil_life_low_pct ?? 15

  const thresholdSnapshot = React.useMemo<ThresholdSnapshot>(() => ({ wpLow, battLow, sigLow }), [wpLow, battLow, sigLow])

  const filtered = React.useMemo(() => {
    const q = filterText.trim().toLowerCase()
    return devices.filter((d) => {
      if (statusFilter !== 'all' && d.status !== statusFilter) return false
      if (openAlertsOnly && openAlertsReady && !openAlertDeviceIds.has(d.device_id)) return false
      if (!q) return true
      return d.device_id.toLowerCase().includes(q) || d.display_name.toLowerCase().includes(q)
    })
  }, [devices, filterText, statusFilter, openAlertsOnly, openAlertsReady, openAlertDeviceIds])

  const cols = React.useMemo<ColumnDef<DeviceSummaryOut>[]>(() => {
    return [
      {
        header: 'Status',
        accessorKey: 'status',
        cell: (info) => {
          const s = info.getValue() as DeviceSummaryOut['status']
          const hasOpenAlerts = openAlertDeviceIds.has(info.row.original.device_id)
          return (
            <div className="flex flex-wrap items-center gap-1">
              <Badge variant={statusVariant(s)}>{s}</Badge>
              {hasOpenAlerts ? <Badge variant="warning">open alerts</Badge> : null}
            </div>
          )
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
        header: 'Health',
        id: 'health',
        cell: (info) => {
          const d = info.row.original
          const health = computeFleetHealth(d, thresholdSnapshot, openAlertDeviceIds.has(d.device_id))
          return (
            <div className="space-y-1">
              <Badge variant={health.variant}>{health.label}</Badge>
              <div className="max-w-[26rem] text-xs text-muted-foreground">{health.detail}</div>
            </div>
          )
        },
      },
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
  }, [wpLow, oilPressureLow, oilLevelLow, dripOilLevelLow, oilLifeLow, battLow, sigLow, thresholdSnapshot, openAlertDeviceIds])

  const counts = React.useMemo(() => {
    const total = devices.length
    const online = devices.filter((d) => d.status === 'online').length
    const offline = devices.filter((d) => d.status === 'offline').length
    const unknown = devices.filter((d) => d.status === 'unknown').length
    const withOpenAlerts = devices.filter((d) => openAlertDeviceIds.has(d.device_id)).length
    return { total, online, offline, unknown, withOpenAlerts }
  }, [devices, openAlertDeviceIds])

  const clearFilters = React.useCallback(() => {
    setFilterText('')
    setStatusFilter('all')
    setOpenAlertsOnly(false)
  }, [])

  const emptyState = React.useMemo(() => {
    if (devicesQ.isLoading) return 'Loading devices…'
    if (devices.length === 0) {
      return (
        <div className="space-y-1">
          <div>No devices are registered yet.</div>
          <div>
            Register one in Admin, or run <code className="font-mono">make demo-device</code> then{' '}
            <code className="font-mono">make simulate</code>.
          </div>
        </div>
      )
    }
    if (openAlertsOnly && openAlertsReady) {
      return 'No devices currently have open alerts. Disable "open alerts only" to see the full fleet.'
    }
    if (filterText.trim() || statusFilter !== 'all') {
      return (
        <div className="space-y-2">
          <div>No devices match the current filters.</div>
          <Button variant="outline" size="sm" onClick={clearFilters}>
            Clear filters
          </Button>
        </div>
      )
    }
    return 'No devices.'
  }, [devicesQ.isLoading, devices.length, openAlertsOnly, openAlertsReady, filterText, statusFilter, clearFilters])

  return (
    <Page
      title="Devices"
      description="Searchable fleet table with quick filters, health reasons, and latest vitals."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">total: {counts.total}</Badge>
          <Badge variant="success">online: {counts.online}</Badge>
          <Badge variant="destructive">offline: {counts.offline}</Badge>
          <Badge variant="secondary">unknown: {counts.unknown}</Badge>
          <Badge variant="warning">with open alerts: {counts.withOpenAlerts}</Badge>
          {devicesQ.isFetching ? <Badge variant="secondary">refreshing…</Badge> : null}
          {openAlertsQ.isFetching ? <Badge variant="secondary">loading alerts…</Badge> : null}
        </div>
      }
    >
      <Card>
        <CardHeader>
          <CardTitle>Fleet</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="search">Search</Label>
              <Input
                id="search"
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                placeholder="device id or name"
              />
              <div className="flex items-center gap-2">
                <div className="text-xs text-muted-foreground">Tip: paste a full device id to jump fast.</div>
                <Button variant="outline" size="sm" onClick={clearFilters}>
                  Clear filters
                </Button>
              </div>
            </div>

            <div className="space-y-2">
              <Label>Status</Label>
              <div className="flex flex-wrap gap-2">
                {(['all', 'online', 'offline', 'unknown'] as const).map((s) => (
                  <Badge
                    key={s}
                    variant={s === 'all' ? 'outline' : statusVariant(s)}
                    className={
                      'cursor-pointer select-none ' +
                      (statusFilter === s ? 'ring-2 ring-primary ring-offset-2 ring-offset-background' : 'opacity-80')
                    }
                    onClick={() => setStatusFilter(s)}
                  >
                    {s}
                  </Badge>
                ))}
                <Badge
                  variant={openAlertsOnly ? 'warning' : 'outline'}
                  className={
                    'cursor-pointer select-none ' +
                    (openAlertsOnly ? 'ring-2 ring-primary ring-offset-2 ring-offset-background' : 'opacity-80')
                  }
                  onClick={() => setOpenAlertsOnly((v) => !v)}
                >
                  open alerts only
                </Badge>
              </div>
              <div className="text-xs text-muted-foreground">
                Thresholds: water &lt; {wpLow.toFixed(1)} psi, battery &lt; {battLow.toFixed(2)} V, rssi &lt; {sigLow} dBm
                {edgePolicyQ.isLoading ? ' (loading policy...)' : ''}
              </div>
            </div>

          </div>

          {devicesQ.isLoading ? <div className="text-sm text-muted-foreground">Loading...</div> : null}
          {devicesQ.isError ? <div className="text-sm text-destructive">Error: {(devicesQ.error as Error).message}</div> : null}
          {openAlertsQ.isError ? (
            <div className="text-sm text-destructive">
              Open-alert filter unavailable: {(openAlertsQ.error as Error).message}
            </div>
          ) : null}

          <DataTable<DeviceSummaryOut> data={filtered} columns={cols} height={560} enableSorting emptyState={emptyState} />
        </CardContent>
      </Card>
    </Page>
  )
}
