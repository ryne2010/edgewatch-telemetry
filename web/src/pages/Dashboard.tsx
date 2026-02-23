import React from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link, useNavigate } from '@tanstack/react-router'
import { api, type AlertOut, type DeviceSummaryOut } from '../api'
import { FleetMap } from '../components/FleetMap'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Page } from '../ui-kit'
import type { Point } from '../ui/LineChart'
import { Sparkline } from '../ui/Sparkline'
import { fmtAlertType, fmtDateTime, timeAgo } from '../utils/format'

type SeverityFilter = 'all' | 'critical' | 'warning' | 'info'
type SeverityKind = Exclude<SeverityFilter, 'all'>
type TimelineWindowHours = 24 | 72 | 168 | 336

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

const TIMELINE_WINDOWS: Array<{ hours: TimelineWindowHours; label: string }> = [
  { hours: 24, label: '24h' },
  { hours: 72, label: '72h' },
  { hours: 168, label: '7d' },
  { hours: 336, label: '14d' },
]

function statusVariant(status: DeviceSummaryOut['status']): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (status === 'online') return 'success'
  if (status === 'offline') return 'destructive'
  return 'secondary'
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

function asNumber(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
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

  return {
    start,
    end,
    totals: {
      total: counts.total.reduce((a, b) => a + b, 0),
      critical: counts.critical.reduce((a, b) => a + b, 0),
      warning: counts.warning.reduce((a, b) => a + b, 0),
      info: counts.info.reduce((a, b) => a + b, 0),
    },
    series: {
      total: toPoints(counts.total),
      critical: toPoints(counts.critical),
      warning: toPoints(counts.warning),
      info: toPoints(counts.info),
    },
  }
}

function buildTimelineGroups(rows: AlertOut[], maxGroups = 6): TimelineGroup[] {
  const sorted = [...rows].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
  const map = new Map<string, TimelineGroup>()

  for (const row of sorted) {
    const ts = Date.parse(row.created_at)
    if (!Number.isFinite(ts)) continue

    const day = new Date(ts)
    const dayKey = day.toISOString().slice(0, 10)
    const dayLabel = day.toLocaleDateString(undefined, {
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

function topCounts(rows: AlertOut[], pick: (row: AlertOut) => string, limit = 5): Array<{ key: string; count: number }> {
  const map = new Map<string, number>()
  for (const row of rows) {
    const key = pick(row).trim()
    if (!key) continue
    map.set(key, (map.get(key) ?? 0) + 1)
  }
  return Array.from(map.entries())
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key))
    .slice(0, limit)
}

function isResolutionAlertType(alertType: string): boolean {
  const t = (alertType ?? '').toUpperCase()
  return t === 'DEVICE_ONLINE' || t.endsWith('_OK')
}

function TopDeviceLinks(props: { deviceIds: string[] }) {
  const ids = props.deviceIds.slice(0, 5)
  if (!ids.length) return null
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      {ids.map((id) => (
        <Link
          key={id}
          to="/devices/$deviceId"
          params={{ deviceId: id }}
          className="rounded-md border bg-background px-2 py-1 font-mono text-[11px] text-muted-foreground hover:text-foreground"
        >
          {id}
        </Link>
      ))}
    </div>
  )
}

export function DashboardPage() {
  const navigate = useNavigate()
  const [timelineWindowHours, setTimelineWindowHours] = React.useState<TimelineWindowHours>(168)
  const [timelineOpenOnly, setTimelineOpenOnly] = React.useState(true)
  const [timelineSeverity, setTimelineSeverity] = React.useState<SeverityFilter>('all')
  const [timelineSelectedDayKey, setTimelineSelectedDayKey] = React.useState<'all' | string>('all')
  const [timelineExpanded, setTimelineExpanded] = React.useState(false)

  const tileCardProps = React.useCallback(
    (href: string) => ({
      role: 'button' as const,
      tabIndex: 0,
      className:
        'cursor-pointer transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
      onClick: (event: React.MouseEvent<HTMLDivElement>) => {
        const interactive = (event.target as HTMLElement | null)?.closest(
          'a,button,input,textarea,select,[role="button"]',
        )
        if (interactive && interactive !== event.currentTarget) return
        navigate({ href })
      },
      onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => {
        if (event.key !== 'Enter' && event.key !== ' ') return
        const interactive = (event.target as HTMLElement | null)?.closest(
          'a,button,input,textarea,select,[role="button"]',
        )
        if (interactive && interactive !== event.currentTarget) return
        event.preventDefault()
        navigate({ href })
      },
    }),
    [navigate],
  )

  const healthQ = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 60_000 })
  const edgePolicyQ = useQuery({ queryKey: ['edgePolicyContract'], queryFn: api.edgePolicyContract, staleTime: 5 * 60_000 })

  const devicesQ = useQuery({
    queryKey: ['devicesSummary', 'vitals'],
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
        'latitude',
        'longitude',
        'lat',
        'lon',
        'lng',
        'gps_latitude',
        'gps_longitude',
        'location_lat',
        'location_lon',
      ],
      }),
    refetchInterval: 10_000,
  })

  const openAlertsQ = useQuery({
    queryKey: ['alerts', 'open'],
    queryFn: () => api.alerts({ open_only: true, limit: 50 }),
    refetchInterval: 15_000,
  })

  const timelineAlertsQ = useQuery({
    queryKey: ['alerts', 'timeline', timelineOpenOnly],
    queryFn: () =>
      api.alerts({
        limit: 500,
        open_only: timelineOpenOnly ? true : undefined,
      }),
    refetchInterval: 15_000,
  })

  const devices = devicesQ.data ?? []
  const openAlerts = openAlertsQ.data ?? []
  const actionableOpenAlerts = React.useMemo(
    () => openAlerts.filter((row) => !isResolutionAlertType(row.alert_type)),
    [openAlerts],
  )

  const thresholds = edgePolicyQ.data?.alert_thresholds
  const wpLow = thresholds?.water_pressure_low_psi ?? 20
  const battLow = thresholds?.battery_low_v ?? 11.8
  const sigLow = thresholds?.signal_low_rssi_dbm ?? -95

  const oilPressureLow = thresholds?.oil_pressure_low_psi ?? 20
  const oilLevelLow = thresholds?.oil_level_low_pct ?? 20
  const dripOilLevelLow = thresholds?.drip_oil_level_low_pct ?? 20
  const oilLifeLow = thresholds?.oil_life_low_pct ?? 15

  const counts = React.useMemo(() => {
    const total = devices.length
    const online = devices.filter((d) => d.status === 'online').length
    const offline = devices.filter((d) => d.status === 'offline').length
    const unknown = devices.filter((d) => d.status === 'unknown').length
    return { total, online, offline, unknown }
  }, [devices])

  const offlineDevices = React.useMemo(() => {
    return devices
      .filter((d) => d.status === 'offline')
      .slice()
      .sort((a, b) => (b.seconds_since_last_seen ?? 0) - (a.seconds_since_last_seen ?? 0))
      .slice(0, 10)
  }, [devices])

  const noTelemetry = React.useMemo(() => devices.filter((d) => !d.latest_telemetry_at), [devices])

  const lowWaterPressure = React.useMemo(() => {
    return devices.filter((d) => {
      const v = asNumber(d.metrics?.water_pressure_psi)
      return v != null && v < wpLow
    })
  }, [devices, wpLow])

  const lowBattery = React.useMemo(() => {
    return devices.filter((d) => {
      const v = asNumber(d.metrics?.battery_v)
      return v != null && v < battLow
    })
  }, [devices, battLow])

  const weakSignal = React.useMemo(() => {
    return devices.filter((d) => {
      const v = asNumber(d.metrics?.signal_rssi_dbm)
      return v != null && v < sigLow
    })
  }, [devices, sigLow])

  const lowOilPressure = React.useMemo(() => {
    return devices.filter((d) => {
      const v = asNumber(d.metrics?.oil_pressure_psi)
      return v != null && v < oilPressureLow
    })
  }, [devices, oilPressureLow])

  const lowOilLevel = React.useMemo(() => {
    return devices.filter((d) => {
      const v = asNumber(d.metrics?.oil_level_pct)
      return v != null && v < oilLevelLow
    })
  }, [devices, oilLevelLow])

  const lowDripOil = React.useMemo(() => {
    return devices.filter((d) => {
      const v = asNumber(d.metrics?.drip_oil_level_pct)
      return v != null && v < dripOilLevelLow
    })
  }, [devices, dripOilLevelLow])

  const lowOilLife = React.useMemo(() => {
    return devices.filter((d) => {
      const v = asNumber(d.metrics?.oil_life_pct)
      return v != null && v < oilLifeLow
    })
  }, [devices, oilLifeLow])

  const timelineRange = React.useMemo(() => {
    const end = Date.now()
    const start = end - timelineWindowHours * 60 * 60 * 1000
    return { start, end }
  }, [timelineWindowHours])

  const timelineRows = React.useMemo(() => {
    const rows = timelineAlertsQ.data ?? []
    return rows
      .filter((row) => {
        const ts = Date.parse(row.created_at)
        if (!Number.isFinite(ts) || ts < timelineRange.start || ts > timelineRange.end) return false
        if (timelineOpenOnly && isResolutionAlertType(row.alert_type)) return false
        if (timelineSeverity !== 'all' && sevKind(row.severity) !== timelineSeverity) return false
        return true
      })
      .slice()
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
  }, [timelineAlertsQ.data, timelineRange.start, timelineRange.end, timelineOpenOnly, timelineSeverity])

  const timelineAllGroups = React.useMemo(() => buildTimelineGroups(timelineRows, 90), [timelineRows])
  const timelineGroups = React.useMemo(
    () => timelineAllGroups.slice(0, timelineExpanded ? 14 : 6),
    [timelineAllGroups, timelineExpanded],
  )

  React.useEffect(() => {
    if (timelineSelectedDayKey === 'all') return
    if (!timelineGroups.some((g) => g.dayKey === timelineSelectedDayKey)) {
      setTimelineSelectedDayKey('all')
    }
  }, [timelineGroups, timelineSelectedDayKey])

  const timelineVisibleGroups = React.useMemo(() => {
    if (timelineSelectedDayKey === 'all') return timelineGroups
    const selected = timelineGroups.find((g) => g.dayKey === timelineSelectedDayKey)
    return selected ? [selected] : []
  }, [timelineGroups, timelineSelectedDayKey])

  const timelineScopeRows = React.useMemo(() => {
    if (timelineSelectedDayKey === 'all') return timelineRows
    return timelineVisibleGroups[0]?.rows ?? []
  }, [timelineRows, timelineVisibleGroups, timelineSelectedDayKey])

  const timelineVolumeHours = timelineSelectedDayKey === 'all' ? timelineWindowHours : 24
  const timelineVolume = React.useMemo(
    () => buildVolumeSeries(timelineScopeRows, { hours: timelineVolumeHours }),
    [timelineScopeRows, timelineVolumeHours],
  )

  const timelineTotals = React.useMemo(() => {
    return timelineScopeRows.reduce(
      (acc, row) => {
        const k = sevKind(row.severity)
        acc.total += 1
        acc[k] += 1
        return acc
      },
      { total: 0, critical: 0, warning: 0, info: 0 },
    )
  }, [timelineScopeRows])

  const timelineDistinctDevices = React.useMemo(() => {
    return new Set(timelineScopeRows.map((row) => row.device_id)).size
  }, [timelineScopeRows])

  const timelineTopDevices = React.useMemo(() => {
    return topCounts(timelineScopeRows, (row) => row.device_id)
  }, [timelineScopeRows])

  const timelineTopTypes = React.useMemo(() => {
    return topCounts(timelineScopeRows, (row) => fmtAlertType(row.alert_type))
  }, [timelineScopeRows])

  const timelineLatest = timelineScopeRows[0] ?? null

  const timelinePeakHour = React.useMemo(() => {
    let peak: Point | null = null
    for (const p of timelineVolume.series.total) {
      if (!peak || p.y > peak.y) peak = p
    }
    return peak
  }, [timelineVolume.series.total])

  const timelineAlertsHref = React.useMemo(() => {
    const params = new URLSearchParams()
    params.set('resolution', timelineOpenOnly ? 'open' : 'all')
    if (timelineSeverity !== 'all') params.set('severity', timelineSeverity)
    return `/alerts?${params.toString()}`
  }, [timelineOpenOnly, timelineSeverity])

  const alertCols = React.useMemo<ColumnDef<AlertOut>[]>(() => {
    return [
      {
        header: 'Severity',
        accessorKey: 'severity',
        cell: (info) => <Badge variant={severityVariant(String(info.getValue()))}>{String(info.getValue())}</Badge>,
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
    ]
  }, [])

  const offlineCols = React.useMemo<ColumnDef<DeviceSummaryOut>[]>(() => {
    return [
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
      { header: 'Name', accessorKey: 'display_name' },
      {
        header: 'Last seen',
        accessorKey: 'last_seen_at',
        cell: (info) => <span className="text-muted-foreground">{fmtDateTime(info.getValue() as any)}</span>,
      },
      {
        header: 'Seconds since',
        accessorKey: 'seconds_since_last_seen',
        cell: (info) => {
          const v = info.getValue() as number | null
          return v == null ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            <span className="font-mono text-xs">{v}</span>
          )
        },
      },
    ]
  }, [])

  return (
    <Page
      title="Dashboard"
      description={
        <span>
          Fleet-level view: heartbeat status, vitals, and open alerts.
          {healthQ.data ? ` Environment: ${healthQ.data.env}` : ''}
        </span>
      }
      actions={
        <div className="flex items-center gap-2">
          {healthQ.data ? <Badge variant="outline">env: {healthQ.data.env}</Badge> : null}
          {devicesQ.isFetching ? <Badge variant="secondary">refreshing…</Badge> : null}
        </div>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card {...tileCardProps('/devices')}>
          <CardHeader>
            <CardTitle>Total devices</CardTitle>
            <CardDescription>Fleet size (enabled + disabled)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{counts.total}</div>
          </CardContent>
        </Card>

        <Card {...tileCardProps('/devices?status=online')}>
          <CardHeader>
            <CardTitle>Online</CardTitle>
            <CardDescription>Within offline window</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <div className="text-3xl font-semibold tracking-tight">{counts.online}</div>
              <Badge variant={statusVariant('online')}>online</Badge>
            </div>
          </CardContent>
        </Card>

        <Card {...tileCardProps('/devices?status=offline')}>
          <CardHeader>
            <CardTitle>Offline</CardTitle>
            <CardDescription>Exceeded offline window</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <div className="text-3xl font-semibold tracking-tight">{counts.offline}</div>
              <Badge variant={statusVariant('offline')}>offline</Badge>
            </div>
          </CardContent>
        </Card>

        <Card {...tileCardProps('/alerts?openOnly=true')}>
          <CardHeader>
            <CardTitle>Open alerts</CardTitle>
            <CardDescription>Actionable unresolved alerts (recovery events excluded)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{actionableOpenAlerts.length}</div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card {...tileCardProps('/devices')}>
          <CardHeader>
            <CardTitle>Low water pressure</CardTitle>
            <CardDescription>
              Below threshold ({wpLow.toFixed(1)} psi)
              {edgePolicyQ.isLoading ? ' — loading policy…' : ''}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{lowWaterPressure.length}</div>
            <TopDeviceLinks deviceIds={lowWaterPressure.map((d) => d.device_id)} />
          </CardContent>
        </Card>

        <Card {...tileCardProps('/devices')}>
          <CardHeader>
            <CardTitle>Low battery</CardTitle>
            <CardDescription>Below threshold ({battLow.toFixed(2)} V)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{lowBattery.length}</div>
            <TopDeviceLinks deviceIds={lowBattery.map((d) => d.device_id)} />
          </CardContent>
        </Card>

        <Card {...tileCardProps('/devices')}>
          <CardHeader>
            <CardTitle>Weak signal</CardTitle>
            <CardDescription>Below threshold ({sigLow} dBm)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{weakSignal.length}</div>
            <TopDeviceLinks deviceIds={weakSignal.map((d) => d.device_id)} />
          </CardContent>
        </Card>

        <Card {...tileCardProps('/devices')}>
          <CardHeader>
            <CardTitle>Low oil pressure</CardTitle>
            <CardDescription>Below threshold ({oilPressureLow.toFixed(1)} psi)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{lowOilPressure.length}</div>
            <TopDeviceLinks deviceIds={lowOilPressure.map((d) => d.device_id)} />
          </CardContent>
        </Card>

        <Card {...tileCardProps('/devices')}>
          <CardHeader>
            <CardTitle>Low oil level</CardTitle>
            <CardDescription>Below threshold ({oilLevelLow.toFixed(1)}%)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{lowOilLevel.length}</div>
            <TopDeviceLinks deviceIds={lowOilLevel.map((d) => d.device_id)} />
          </CardContent>
        </Card>

        <Card {...tileCardProps('/devices')}>
          <CardHeader>
            <CardTitle>Low drip oil</CardTitle>
            <CardDescription>Below threshold ({dripOilLevelLow.toFixed(1)}%)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{lowDripOil.length}</div>
            <TopDeviceLinks deviceIds={lowDripOil.map((d) => d.device_id)} />
          </CardContent>
        </Card>

        <Card {...tileCardProps('/devices')}>
          <CardHeader>
            <CardTitle>Oil life low</CardTitle>
            <CardDescription>Below threshold ({oilLifeLow.toFixed(0)}%)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{lowOilLife.length}</div>
            <TopDeviceLinks deviceIds={lowOilLife.map((d) => d.device_id)} />
          </CardContent>
        </Card>

        <Card {...tileCardProps('/devices')}>
          <CardHeader>
            <CardTitle>No telemetry yet</CardTitle>
            <CardDescription>Devices without a point ingested</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{noTelemetry.length}</div>
            <TopDeviceLinks deviceIds={noTelemetry.map((d) => d.device_id)} />
          </CardContent>
        </Card>
      </div>

      <div className="mt-6">
        <Card>
          <CardHeader>
            <CardTitle>Fleet map</CardTitle>
            <CardDescription>
              Interactive location view with status markers, selected-device details, and open-alert context.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <FleetMap devices={devices} openAlerts={actionableOpenAlerts} />
          </CardContent>
        </Card>
      </div>

      <div className="mt-6">
        <Card>
          <CardHeader>
            <CardTitle>Timeline</CardTitle>
            <CardDescription>
              Incident timeline with window controls, severity mix, top impacted devices, and daily drill-down.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium text-foreground">Window</span>
                {TIMELINE_WINDOWS.map((windowOpt) => (
                  <Button
                    key={windowOpt.hours}
                    variant={timelineWindowHours === windowOpt.hours ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => {
                      setTimelineWindowHours(windowOpt.hours)
                      setTimelineSelectedDayKey('all')
                      setTimelineExpanded(false)
                    }}
                  >
                    {windowOpt.label}
                  </Button>
                ))}

                <span className="ml-2 text-xs font-medium text-foreground">Status</span>
                <Button
                  variant={timelineOpenOnly ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => {
                    setTimelineOpenOnly(true)
                    setTimelineSelectedDayKey('all')
                  }}
                >
                  Open only
                </Button>
                <Button
                  variant={!timelineOpenOnly ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => {
                    setTimelineOpenOnly(false)
                    setTimelineSelectedDayKey('all')
                  }}
                >
                  Open + resolved
                </Button>

                <span className="ml-2 text-xs font-medium text-foreground">Severity</span>
                <Button variant={timelineSeverity === 'all' ? 'default' : 'outline'} size="sm" onClick={() => setTimelineSeverity('all')}>
                  All
                </Button>
                <Button
                  variant={timelineSeverity === 'critical' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setTimelineSeverity('critical')}
                >
                  Critical
                </Button>
                <Button
                  variant={timelineSeverity === 'warning' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setTimelineSeverity('warning')}
                >
                  Warning
                </Button>
                <Button variant={timelineSeverity === 'info' ? 'default' : 'outline'} size="sm" onClick={() => setTimelineSeverity('info')}>
                  Info
                </Button>

                <div className="ml-auto flex items-center gap-2">
                  {timelineAlertsQ.isFetching ? <Badge variant="secondary">refreshing…</Badge> : null}
                  <Button variant="outline" size="sm" onClick={() => navigate({ href: timelineAlertsHref })}>
                    Open in Alerts
                  </Button>
                </div>
              </div>

              {timelineAlertsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading timeline…</div> : null}
              {timelineAlertsQ.isError ? (
                <div className="text-sm text-destructive">Error: {(timelineAlertsQ.error as Error).message}</div>
              ) : null}

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-lg border bg-background p-3">
                  <div className="text-xs text-muted-foreground">Alerts in scope</div>
                  <div className="text-2xl font-semibold tracking-tight">{timelineTotals.total}</div>
                </div>
                <div className="rounded-lg border bg-background p-3">
                  <div className="text-xs text-muted-foreground">Distinct devices</div>
                  <div className="text-2xl font-semibold tracking-tight">{timelineDistinctDevices}</div>
                </div>
                <div className="rounded-lg border bg-background p-3">
                  <div className="text-xs text-muted-foreground">Peak hour</div>
                  <div className="text-sm font-semibold">
                    {timelinePeakHour
                      ? new Date(timelinePeakHour.x).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
                      : '—'}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {timelinePeakHour ? `${timelinePeakHour.y} alert${timelinePeakHour.y === 1 ? '' : 's'}` : 'No peak yet'}
                  </div>
                </div>
                <div className="rounded-lg border bg-background p-3">
                  <div className="text-xs text-muted-foreground">Latest alert</div>
                  <div className="text-sm font-semibold">{timelineLatest ? timeAgo(timelineLatest.created_at) : '—'}</div>
                  <div className="truncate text-xs text-muted-foreground">
                    {timelineLatest ? `${timelineLatest.device_id} · ${fmtAlertType(timelineLatest.alert_type)}` : 'No alerts'}
                  </div>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-lg border bg-background p-3">
                  <div className="text-sm font-medium">Total</div>
                  <div className="text-2xl font-semibold tracking-tight">{timelineVolume.totals.total}</div>
                  <div className="mt-2 text-primary">
                    <Sparkline points={timelineVolume.series.total} height={56} ariaLabel="timeline total alerts sparkline" />
                  </div>
                </div>
                <div className="rounded-lg border bg-background p-3">
                  <div className="text-sm font-medium">Critical</div>
                  <div className="text-2xl font-semibold tracking-tight">{timelineVolume.totals.critical}</div>
                  <div className="mt-2 text-destructive">
                    <Sparkline points={timelineVolume.series.critical} height={56} ariaLabel="timeline critical alerts sparkline" />
                  </div>
                </div>
                <div className="rounded-lg border bg-background p-3">
                  <div className="text-sm font-medium">Warning</div>
                  <div className="text-2xl font-semibold tracking-tight">{timelineVolume.totals.warning}</div>
                  <div className="mt-2 text-amber-600">
                    <Sparkline points={timelineVolume.series.warning} height={56} ariaLabel="timeline warning alerts sparkline" />
                  </div>
                </div>
                <div className="rounded-lg border bg-background p-3">
                  <div className="text-sm font-medium">Info</div>
                  <div className="text-2xl font-semibold tracking-tight">{timelineVolume.totals.info}</div>
                  <div className="mt-2 text-muted-foreground">
                    <Sparkline points={timelineVolume.series.info} height={56} ariaLabel="timeline info alerts sparkline" />
                  </div>
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      variant={timelineSelectedDayKey === 'all' ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setTimelineSelectedDayKey('all')}
                    >
                      All days
                    </Button>
                    {timelineGroups.map((g) => (
                      <Button
                        key={g.dayKey}
                        variant={timelineSelectedDayKey === g.dayKey ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => setTimelineSelectedDayKey(g.dayKey)}
                      >
                        {g.dayLabel} ({g.totals.total})
                      </Button>
                    ))}
                  </div>

                  {timelineVisibleGroups.length === 0 ? (
                    <div className="rounded-lg border bg-background p-4 text-sm text-muted-foreground">
                      No alerts in this window.
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {timelineVisibleGroups.map((g) => (
                        <div key={g.dayKey} className="rounded-lg border bg-background p-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <div className="text-sm font-semibold">{g.dayLabel}</div>
                            <Badge variant="outline">total: {g.totals.total}</Badge>
                            <Badge variant="destructive">critical: {g.totals.critical}</Badge>
                            <Badge variant="warning">warning: {g.totals.warning}</Badge>
                            <Badge variant="secondary">info: {g.totals.info}</Badge>
                          </div>
                          <div className="mt-2 space-y-1">
                            {g.rows.slice(0, 5).map((row) => (
                              <div key={row.id} className="grid gap-2 text-xs sm:grid-cols-[7rem_9rem_10rem_1fr]">
                                <div className="font-mono text-muted-foreground">
                                  {new Date(row.created_at).toLocaleTimeString(undefined, {
                                    hour: '2-digit',
                                    minute: '2-digit',
                                    second: '2-digit',
                                    hour12: false,
                                  })}
                                </div>
                                <div>
                                  <Badge variant={severityVariant(row.severity)}>{row.severity}</Badge>
                                </div>
                                <Link to="/devices/$deviceId" params={{ deviceId: row.device_id }} className="font-mono text-muted-foreground">
                                  {row.device_id}
                                </Link>
                                <div className="truncate text-muted-foreground">
                                  {fmtAlertType(row.alert_type)} · {row.message}
                                </div>
                              </div>
                            ))}
                            {g.rows.length > 5 ? (
                              <div className="text-xs text-muted-foreground">+ {g.rows.length - 5} more in this day</div>
                            ) : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="space-y-3">
                  <div className="rounded-lg border bg-background p-3">
                    <div className="text-sm font-medium">Top devices</div>
                    <div className="mt-2 space-y-1">
                      {timelineTopDevices.length === 0 ? (
                        <div className="text-xs text-muted-foreground">No impacted devices in scope.</div>
                      ) : (
                        timelineTopDevices.map((row) => (
                          <div key={row.key} className="flex items-center justify-between gap-2 text-xs">
                            <Link to="/devices/$deviceId" params={{ deviceId: row.key }} className="font-mono text-muted-foreground">
                              {row.key}
                            </Link>
                            <Badge variant="outline">{row.count}</Badge>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  <div className="rounded-lg border bg-background p-3">
                    <div className="text-sm font-medium">Top alert types</div>
                    <div className="mt-2 space-y-1">
                      {timelineTopTypes.length === 0 ? (
                        <div className="text-xs text-muted-foreground">No alert types in scope.</div>
                      ) : (
                        timelineTopTypes.map((row) => (
                          <div key={row.key} className="flex items-center justify-between gap-2 text-xs">
                            <span className="truncate text-muted-foreground">{row.key}</span>
                            <Badge variant="outline">{row.count}</Badge>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                <div>
                  Coverage: {new Date(timelineVolume.start).toLocaleString()} {'->'} {new Date(timelineVolume.end).toLocaleString()}.
                </div>
                {timelineSelectedDayKey === 'all' && timelineAllGroups.length > 6 ? (
                  <Button variant="outline" size="sm" onClick={() => setTimelineExpanded((v) => !v)}>
                    {timelineExpanded ? 'Show fewer days' : 'Show more days'}
                  </Button>
                ) : null}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Open alerts</CardTitle>
            <CardDescription>
              Most recent actionable unresolved alerts. See{' '}
              <Link to="/alerts" className="underline">
                Alerts
              </Link>{' '}
              for filters.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {openAlertsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
            {openAlertsQ.isError ? (
              <div className="text-sm text-destructive">Error: {(openAlertsQ.error as Error).message}</div>
            ) : null}
            <DataTable<AlertOut>
              data={actionableOpenAlerts.slice(0, 10)}
              columns={alertCols}
              height={360}
              enableSorting
              emptyState="No actionable open alerts."
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Offline devices</CardTitle>
            <CardDescription>
              Highest “seconds since last seen” first. See{' '}
              <Link to="/devices" className="underline">
                Devices
              </Link>
              .
            </CardDescription>
          </CardHeader>
          <CardContent>
            <DataTable<DeviceSummaryOut>
              data={offlineDevices}
              columns={offlineCols}
              height={360}
              enableSorting
              emptyState="No offline devices."
            />
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}
