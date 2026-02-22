import React from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link } from '@tanstack/react-router'
import { api, type AlertOut, type DeviceSummaryOut } from '../api'
import { FleetMap } from '../components/FleetMap'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Page } from '../ui-kit'
import { fmtAlertType, fmtDateTime, timeAgo } from '../utils/format'

function statusVariant(status: DeviceSummaryOut['status']): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (status === 'online') return 'success'
  if (status === 'offline') return 'destructive'
  return 'secondary'
}

function severityVariant(sev: string): 'success' | 'warning' | 'destructive' | 'secondary' {
  const s = (sev ?? '').toLowerCase()
  if (s === 'critical' || s === 'high' || s === 'error') return 'destructive'
  if (s === 'warn' || s === 'warning' || s === 'medium') return 'warning'
  return 'secondary'
}

function asNumber(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
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

  const devices = devicesQ.data ?? []
  const openAlerts = openAlertsQ.data ?? []

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
        <Card>
          <CardHeader>
            <CardTitle>Total devices</CardTitle>
            <CardDescription>Fleet size (enabled + disabled)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{counts.total}</div>
          </CardContent>
        </Card>

        <Card>
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

        <Card>
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

        <Card>
          <CardHeader>
            <CardTitle>Open alerts</CardTitle>
            <CardDescription>Unresolved alerts (latest 50)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{openAlerts.length}</div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
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

        <Card>
          <CardHeader>
            <CardTitle>Low battery</CardTitle>
            <CardDescription>Below threshold ({battLow.toFixed(2)} V)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{lowBattery.length}</div>
            <TopDeviceLinks deviceIds={lowBattery.map((d) => d.device_id)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Weak signal</CardTitle>
            <CardDescription>Below threshold ({sigLow} dBm)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{weakSignal.length}</div>
            <TopDeviceLinks deviceIds={weakSignal.map((d) => d.device_id)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Low oil pressure</CardTitle>
            <CardDescription>Below threshold ({oilPressureLow.toFixed(1)} psi)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{lowOilPressure.length}</div>
            <TopDeviceLinks deviceIds={lowOilPressure.map((d) => d.device_id)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Low oil level</CardTitle>
            <CardDescription>Below threshold ({oilLevelLow.toFixed(1)}%)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{lowOilLevel.length}</div>
            <TopDeviceLinks deviceIds={lowOilLevel.map((d) => d.device_id)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Low drip oil</CardTitle>
            <CardDescription>Below threshold ({dripOilLevelLow.toFixed(1)}%)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{lowDripOil.length}</div>
            <TopDeviceLinks deviceIds={lowDripOil.map((d) => d.device_id)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Oil life low</CardTitle>
            <CardDescription>Below threshold ({oilLifeLow.toFixed(0)}%)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{lowOilLife.length}</div>
            <TopDeviceLinks deviceIds={lowOilLife.map((d) => d.device_id)} />
          </CardContent>
        </Card>

        <Card>
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
            <FleetMap devices={devices} openAlerts={openAlerts} />
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Open alerts</CardTitle>
            <CardDescription>
              Most recent unresolved alerts. See{' '}
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
              data={openAlerts.slice(0, 10)}
              columns={alertCols}
              height={360}
              enableSorting
              emptyState="No open alerts."
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
