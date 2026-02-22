import React from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link, useParams } from '@tanstack/react-router'
import {
  api,
  type DriftEventOut,
  type IngestionBatchOut,
  type MediaObjectOut,
  type NotificationEventOut,
  type TelemetryContract,
  type TelemetryPoint,
  type TimeseriesMultiPoint,
} from '../api'
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
  Skeleton,
  useToast,
} from '../ui-kit'
import { useAppSettings } from '../app/settings'
import { fmtDateTime, fmtNumber } from '../utils/format'
import { adminAccessHint } from '../utils/adminAuth'

type Bucket = 'minute' | 'hour'
type TabKey = 'overview' | 'telemetry' | 'ingestions' | 'drift' | 'notifications' | 'media'
type CameraFilter = 'all' | 'cam1' | 'cam2' | 'cam3' | 'cam4'

const MEDIA_TOKEN_STORAGE_KEY = 'edgewatch_media_tokens_v1'
const CAMERA_FILTERS: CameraFilter[] = ['all', 'cam1', 'cam2', 'cam3', 'cam4']

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

function getStoredMediaToken(deviceId: string): string {
  try {
    const raw = localStorage.getItem(MEDIA_TOKEN_STORAGE_KEY)
    if (!raw) return ''
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object') return ''
    const v = (parsed as Record<string, unknown>)[deviceId]
    return typeof v === 'string' ? v : ''
  } catch {
    return ''
  }
}

function storeMediaToken(deviceId: string, token: string): void {
  const normalized = token.trim()
  try {
    const raw = localStorage.getItem(MEDIA_TOKEN_STORAGE_KEY)
    const parsed = raw ? (JSON.parse(raw) as unknown) : {}
    const out: Record<string, string> = parsed && typeof parsed === 'object' ? { ...(parsed as Record<string, string>) } : {}
    if (normalized) out[deviceId] = normalized
    else delete out[deviceId]
    localStorage.setItem(MEDIA_TOKEN_STORAGE_KEY, JSON.stringify(out))
  } catch {
    // best effort only
  }
}

function reasonLabel(reason: string): string {
  const r = reason.trim().toLowerCase()
  if (r === 'scheduled') return 'Scheduled'
  if (r === 'alert_transition') return 'Alert transition'
  if (r === 'manual') return 'Manual'
  return reason || '—'
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let amount = value
  let unit = units[0]
  for (const next of units) {
    unit = next
    if (amount < 1024 || next === units[units.length - 1]) break
    amount /= 1024
  }
  const digits = amount >= 100 ? 0 : amount >= 10 ? 1 : 2
  return `${amount.toFixed(digits)} ${unit}`
}

function isImageMime(mimeType: string): boolean {
  return mimeType.toLowerCase().startsWith('image/')
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value))
}

function oilLifeState(percent: number): {
  label: string
  note: string
  variant: 'success' | 'warning' | 'destructive' | 'secondary'
  strokeColor: string
} {
  if (percent >= 50) {
    return {
      label: 'Healthy',
      note: 'No immediate service required.',
      variant: 'success',
      strokeColor: 'hsl(var(--primary))',
    }
  }
  if (percent >= 20) {
    return {
      label: 'Watch',
      note: 'Schedule maintenance soon.',
      variant: 'warning',
      strokeColor: 'hsl(38 92% 50%)',
    }
  }
  return {
    label: 'Service now',
    note: 'Oil life is low and should be reset after service.',
    variant: 'destructive',
    strokeColor: 'hsl(var(--destructive))',
  }
}

function OilLifeGauge(props: { percent: number | null; updatedAt?: string; hasMetric: boolean }) {
  if (!props.hasMetric) {
    return (
      <div className="text-sm text-muted-foreground">
        <span className="font-mono">oil_life_pct</span> is not defined in the active telemetry contract.
      </div>
    )
  }
  if (props.percent === null) {
    return <div className="text-sm text-muted-foreground">No oil life value has been reported yet.</div>
  }

  const pct = clampPercent(props.percent)
  const state = oilLifeState(pct)
  const radius = 50
  const circumference = 2 * Math.PI * radius
  const filled = (pct / 100) * circumference

  return (
    <div className="grid gap-5 lg:grid-cols-[13rem_1fr]">
      <div className="mx-auto w-full max-w-[13rem]">
        <div className="relative aspect-square">
          <svg viewBox="0 0 120 120" className="h-full w-full" role="img" aria-label={`Oil life ${fmtNumber(pct, { digits: 0 })} percent`}>
            <circle cx="60" cy="60" r={radius} fill="none" stroke="hsl(var(--muted))" strokeWidth="12" />
            <circle
              cx="60"
              cy="60"
              r={radius}
              fill="none"
              stroke={state.strokeColor}
              strokeWidth="12"
              strokeLinecap="round"
              transform="rotate(-90 60 60)"
              strokeDasharray={`${filled} ${circumference - filled}`}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1">
            <div className="text-3xl font-semibold tracking-tight">{fmtNumber(pct, { digits: 0 })}%</div>
            <Badge variant={state.variant}>{state.label}</Badge>
          </div>
        </div>
      </div>
      <div className="space-y-2 text-sm">
        <div className="text-muted-foreground">{state.note}</div>
        <div className="rounded-md border bg-muted/20 p-3">
          <div className="font-medium">Service thresholds</div>
          <div className="mt-1 text-xs text-muted-foreground">Healthy: 50%+</div>
          <div className="text-xs text-muted-foreground">Watch: 20% to 49%</div>
          <div className="text-xs text-muted-foreground">Service now: below 20%</div>
        </div>
        {props.updatedAt ? (
          <div className="text-xs text-muted-foreground">
            Last telemetry point: <span className="font-mono">{fmtDateTime(props.updatedAt)}</span>
          </div>
        ) : null}
      </div>
    </div>
  )
}

function MediaThumbnail(props: { media: MediaObjectOut; token: string }) {
  const isImage = isImageMime(props.media.mime_type)
  const thumbQ = useQuery({
    queryKey: ['mediaThumb', props.media.id, props.token],
    queryFn: () => api.media.downloadBlob(props.media.id, props.token),
    enabled: isImage && Boolean(props.token),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  })

  const [thumbUrl, setThumbUrl] = React.useState<string>('')
  React.useEffect(() => {
    if (!thumbQ.data) return
    const url = URL.createObjectURL(thumbQ.data)
    setThumbUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return url
    })
    return () => URL.revokeObjectURL(url)
  }, [thumbQ.data])

  if (!isImage) {
    return (
      <div className="flex h-32 items-center justify-center text-xs text-muted-foreground">
        Preview unavailable ({props.media.mime_type})
      </div>
    )
  }
  if (thumbQ.isLoading) return <Skeleton className="h-32 w-full" />
  if (thumbQ.isError) {
    return (
      <div className="flex h-32 items-center justify-center px-2 text-center text-xs text-muted-foreground">
        Preview failed
      </div>
    )
  }
  if (!thumbUrl) return <Skeleton className="h-32 w-full" />

  return <img src={thumbUrl} alt={`${props.media.camera_id} capture`} className="h-32 w-full object-cover" loading="lazy" />
}

export function DeviceDetailPage() {
  const { deviceId } = useParams({ from: '/devices/$deviceId' })
  const { adminKey } = useAppSettings()
  const { toast } = useToast()

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
  const [mediaFilter, setMediaFilter] = React.useState<string>('all')
  const [mediaTokenInput, setMediaTokenInput] = React.useState<string>(() => getStoredMediaToken(deviceId))
  const [mediaToken, setMediaToken] = React.useState<string>(() => getStoredMediaToken(deviceId))
  const [selectedMedia, setSelectedMedia] = React.useState<MediaObjectOut | null>(null)
  const [selectedMediaUrl, setSelectedMediaUrl] = React.useState<string>('')
  const [openingMediaId, setOpeningMediaId] = React.useState<string | null>(null)
  const mediaErrorToastRef = React.useRef<string>('')

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
  const ingestionsAccessHint = React.useMemo(
    () => adminAccessHint(ingestionsQ.error, adminAuthMode),
    [ingestionsQ.error, adminAuthMode],
  )
  const driftAccessHint = React.useMemo(() => adminAccessHint(driftQ.error, adminAuthMode), [driftQ.error, adminAuthMode])
  const notificationsAccessHint = React.useMemo(
    () => adminAccessHint(notificationsQ.error, adminAuthMode),
    [notificationsQ.error, adminAuthMode],
  )

  const mediaQ = useQuery({
    queryKey: ['media', deviceId, mediaToken],
    queryFn: () => api.media.list(deviceId, { token: mediaToken, limit: 200 }),
    enabled: tab === 'media' && Boolean(mediaToken),
    staleTime: 30_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })

  const latestMetrics = latestQ.data?.metrics ?? null
  const oilLifePercent = React.useMemo(() => {
    const value = (latestMetrics as Record<string, unknown> | null)?.oil_life_pct
    if (typeof value !== 'number' || !Number.isFinite(value)) return null
    return clampPercent(value)
  }, [latestMetrics])

  React.useEffect(() => {
    const stored = getStoredMediaToken(deviceId)
    setMediaTokenInput(stored)
    setMediaToken(stored)
    setMediaFilter('all')
    setSelectedMedia(null)
    setSelectedMediaUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return ''
    })
    setOpeningMediaId(null)
    mediaErrorToastRef.current = ''
  }, [deviceId])

  React.useEffect(() => {
    return () => {
      if (selectedMediaUrl) URL.revokeObjectURL(selectedMediaUrl)
    }
  }, [selectedMediaUrl])

  React.useEffect(() => {
    if (tab !== 'media') return
    if (!mediaQ.error) return
    const message = (mediaQ.error as Error).message
    if (mediaErrorToastRef.current === message) return
    mediaErrorToastRef.current = message
    toast({
      title: 'Media load failed',
      description: message,
      variant: 'error',
      durationMs: 8000,
    })
  }, [mediaQ.error, tab, toast])

  React.useEffect(() => {
    if (mediaQ.isSuccess) mediaErrorToastRef.current = ''
  }, [mediaQ.isSuccess])

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

  const mediaRows = mediaQ.data ?? []
  const mediaFilteredRows = React.useMemo(() => {
    if (mediaFilter === 'all') return mediaRows
    return mediaRows.filter((row) => row.camera_id === mediaFilter)
  }, [mediaRows, mediaFilter])
  const mediaGridRows = React.useMemo(() => mediaFilteredRows.slice(0, 24), [mediaFilteredRows])
  const latestByCamera = React.useMemo(() => {
    const out: Partial<Record<Exclude<CameraFilter, 'all'>, MediaObjectOut>> = {}
    for (const cam of CAMERA_FILTERS) {
      if (cam === 'all') continue
      const first = mediaRows.find((row) => row.camera_id === cam)
      if (first) out[cam] = first
    }
    return out
  }, [mediaRows])
  const extraCameraFilters = React.useMemo(() => {
    return Array.from(new Set(mediaRows.map((row) => row.camera_id)))
      .filter((cameraId) => !CAMERA_FILTERS.includes(cameraId as CameraFilter))
      .sort()
  }, [mediaRows])

  const handleMediaTokenSave = React.useCallback(() => {
    const normalized = mediaTokenInput.trim()
    storeMediaToken(deviceId, normalized)
    setMediaToken(normalized)
    if (normalized) {
      toast({
        title: 'Media token saved',
        description: 'Stored for this device in local browser storage.',
        variant: 'success',
      })
    } else {
      toast({ title: 'Media token cleared', variant: 'default' })
    }
  }, [deviceId, mediaTokenInput, toast])

  const handleMediaTokenClear = React.useCallback(() => {
    storeMediaToken(deviceId, '')
    setMediaTokenInput('')
    setMediaToken('')
    setSelectedMedia(null)
    setSelectedMediaUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return ''
    })
    toast({ title: 'Media token cleared', variant: 'default' })
  }, [deviceId, toast])

  const handleCopyMediaLink = React.useCallback(
    async (media: MediaObjectOut) => {
      const url = `${window.location.origin}${api.media.downloadPath(media.id)}`
      try {
        await navigator.clipboard.writeText(url)
        toast({
          title: 'Copied link',
          description: 'Share this link with operators who have device access.',
          variant: 'success',
        })
      } catch {
        toast({
          title: 'Copy failed',
          description: 'Clipboard is not available in this browser context.',
          variant: 'error',
        })
      }
    },
    [toast],
  )

  const handleOpenMedia = React.useCallback(
    async (media: MediaObjectOut) => {
      if (!mediaToken) {
        toast({
          title: 'Device token required',
          description: 'Configure a media token before opening assets.',
          variant: 'warning',
        })
        return
      }
      setOpeningMediaId(media.id)
      try {
        const blob = await api.media.downloadBlob(media.id, mediaToken)
        const url = URL.createObjectURL(blob)
        setSelectedMedia(media)
        setSelectedMediaUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev)
          return url
        })
      } catch (error) {
        toast({
          title: 'Unable to open media',
          description: (error as Error).message,
          variant: 'error',
          durationMs: 8000,
        })
      } finally {
        setOpeningMediaId(null)
      }
    },
    [mediaToken, toast],
  )

  const closeMediaModal = React.useCallback(() => {
    setSelectedMedia(null)
    setSelectedMediaUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return ''
    })
  }, [])

  const tabs: Array<{ key: TabKey; label: string; requiresAdminRoutes?: boolean }> = [
    { key: 'overview', label: 'Overview' },
    { key: 'telemetry', label: 'Telemetry' },
    { key: 'ingestions', label: 'Ingestions', requiresAdminRoutes: true },
    { key: 'drift', label: 'Drift', requiresAdminRoutes: true },
    { key: 'notifications', label: 'Notifications', requiresAdminRoutes: true },
    { key: 'media', label: 'Media' },
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
              <CardTitle>Oil life</CardTitle>
              <CardDescription>Derived runtime estimate from the edge model, shown as a service planning gauge.</CardDescription>
            </CardHeader>
            <CardContent>
              {latestQ.isLoading ? (
                <Skeleton className="h-52 w-full" />
              ) : latestQ.isError ? (
                <div className="text-sm text-destructive">Error: {(latestQ.error as Error).message}</div>
              ) : (
                <OilLifeGauge
                  percent={oilLifePercent}
                  updatedAt={latestQ.data?.ts}
                  hasMetric={Boolean(contract?.metrics?.oil_life_pct)}
                />
              )}
            </CardContent>
          </Card>

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
              {ingestionsQ.isError && ingestionsAccessHint ? (
                <Callout title="Access guidance">{ingestionsAccessHint}</Callout>
              ) : null}
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
              {driftQ.isError && driftAccessHint ? (
                <Callout title="Access guidance">{driftAccessHint}</Callout>
              ) : null}
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
              {notificationsQ.isError && notificationsAccessHint ? (
                <Callout title="Access guidance">{notificationsAccessHint}</Callout>
              ) : null}
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

      {tab === 'media' ? (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Media</CardTitle>
              <CardDescription>
                Device media gallery. One metadata list call per device, with per-item previews and full-resolution open.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 lg:grid-cols-3">
                <div className="space-y-2 lg:col-span-2">
                  <Label>Device media token</Label>
                  <Input
                    type="password"
                    value={mediaTokenInput}
                    onChange={(e) => setMediaTokenInput(e.target.value)}
                    placeholder="Bearer token for this device"
                  />
                  <div className="text-xs text-muted-foreground">
                    Required because media endpoints are device-auth scoped. Stored per-device in local browser storage.
                  </div>
                </div>
                <div className="flex items-end gap-2">
                  <Button onClick={handleMediaTokenSave}>Save token</Button>
                  <Button variant="outline" onClick={handleMediaTokenClear}>
                    Clear
                  </Button>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-3">
                <div className="space-y-2">
                  <Label>Camera filter</Label>
                  <SmallSelect
                    value={mediaFilter}
                    onChange={setMediaFilter}
                    options={[
                      ...CAMERA_FILTERS.map((camera) => ({
                        value: camera,
                        label: camera === 'all' ? 'All cameras' : camera,
                      })),
                      ...extraCameraFilters.map((camera) => ({ value: camera, label: camera })),
                    ]}
                    disabled={!mediaToken}
                  />
                </div>
                <div className="rounded-lg border bg-muted/30 p-3">
                  <div className="text-xs text-muted-foreground">Uploaded items</div>
                  <div className="text-2xl font-semibold tracking-tight">{mediaRows.length}</div>
                </div>
                <div className="rounded-lg border bg-muted/30 p-3">
                  <div className="text-xs text-muted-foreground">Filtered</div>
                  <div className="text-2xl font-semibold tracking-tight">{mediaFilteredRows.length}</div>
                </div>
              </div>

              {!mediaToken ? (
                <Callout title="Token required">
                  Provide the current device token to query media metadata and download assets.
                </Callout>
              ) : null}

              {mediaQ.isLoading ? (
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                  {Array.from({ length: 8 }).map((_, idx) => (
                    <div key={`media-skeleton-${idx}`} className="overflow-hidden rounded-lg border bg-background">
                      <Skeleton className="h-32 w-full rounded-none" />
                      <div className="space-y-2 p-3">
                        <Skeleton className="h-3 w-20" />
                        <Skeleton className="h-3 w-40" />
                        <Skeleton className="h-8 w-full" />
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}

              {!mediaQ.isLoading && mediaToken && mediaRows.length === 0 ? (
                <Callout title="No media yet">
                  This device has no uploaded media objects yet. Capture + upload from the edge agent, then refresh this tab.
                </Callout>
              ) : null}
            </CardContent>
          </Card>

          {mediaRows.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Latest by camera</CardTitle>
                <CardDescription>Most recent item per camera (`cam1..cam4`).</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                  {CAMERA_FILTERS.filter((camera) => camera !== 'all').map((camera) => {
                    const media = latestByCamera[camera]
                    return (
                      <div key={`latest-${camera}`} className="rounded-lg border bg-background p-3">
                        <div className="flex items-center justify-between gap-2">
                          <div className="font-medium">{camera}</div>
                          <Badge variant="outline">{media ? reasonLabel(media.reason) : 'none'}</Badge>
                        </div>
                        {media ? (
                          <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                            <div>{fmtDateTime(media.captured_at)}</div>
                            <div className="font-mono">{formatBytes(media.bytes)}</div>
                          </div>
                        ) : (
                          <div className="mt-2 text-xs text-muted-foreground">No captures yet.</div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </CardContent>
            </Card>
          ) : null}

          {mediaGridRows.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Gallery</CardTitle>
                <CardDescription>
                  Latest {mediaGridRows.length} item(s) for {mediaFilter === 'all' ? 'all cameras' : mediaFilter}.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                  {mediaGridRows.map((media) => (
                    <div key={media.id} className="overflow-hidden rounded-lg border bg-background">
                      <MediaThumbnail media={media} token={mediaToken} />
                      <div className="space-y-2 p-3">
                        <div className="flex items-center justify-between gap-2">
                          <Badge variant="secondary">{media.camera_id}</Badge>
                          <Badge variant="outline">{reasonLabel(media.reason)}</Badge>
                        </div>
                        <div className="text-xs text-muted-foreground">{fmtDateTime(media.captured_at)}</div>
                        <div className="text-xs text-muted-foreground">
                          {formatBytes(media.bytes)} · {media.mime_type}
                        </div>
                        <div className="flex items-center gap-2">
                          <Button
                            size="sm"
                            variant="default"
                            disabled={openingMediaId === media.id}
                            onClick={() => {
                              void handleOpenMedia(media)
                            }}
                          >
                            {openingMediaId === media.id ? 'Opening…' : 'Open'}
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              void handleCopyMediaLink(media)
                            }}
                          >
                            Copy link
                          </Button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ) : null}

          {selectedMedia ? (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm">
              <div className="max-h-[90vh] w-full max-w-5xl overflow-auto rounded-xl border bg-background p-4 shadow-xl">
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-1">
                    <div className="text-lg font-semibold">{selectedMedia.camera_id}</div>
                    <div className="text-sm text-muted-foreground">
                      {fmtDateTime(selectedMedia.captured_at)} · {reasonLabel(selectedMedia.reason)} ·{' '}
                      {formatBytes(selectedMedia.bytes)}
                    </div>
                  </div>
                  <Button variant="outline" onClick={closeMediaModal}>
                    Close
                  </Button>
                </div>

                <div className="mt-4">
                  {selectedMediaUrl && isImageMime(selectedMedia.mime_type) ? (
                    <img
                      src={selectedMediaUrl}
                      alt={`${selectedMedia.camera_id} capture`}
                      className="max-h-[70vh] w-full rounded-md border object-contain"
                    />
                  ) : selectedMediaUrl ? (
                    <Callout title="Preview unavailable">
                      This asset type is not rendered inline in the gallery yet. Use the open/download button below.
                    </Callout>
                  ) : (
                    <div className="rounded-md border bg-muted/30 p-4 text-sm text-muted-foreground">Loading asset…</div>
                  )}
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {selectedMediaUrl ? (
                    <a href={selectedMediaUrl} target="_blank" rel="noreferrer">
                      <Button>Open in new tab</Button>
                    </a>
                  ) : null}
                  <Button
                    variant="outline"
                    onClick={() => {
                      void handleCopyMediaLink(selectedMedia)
                    }}
                  >
                    Copy link
                  </Button>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </Page>
  )
}
