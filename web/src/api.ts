export type DeviceOut = {
  device_id: string
  display_name: string
  heartbeat_interval_s: number
  offline_after_s: number
  last_seen_at: string | null
  enabled: boolean
  status: 'online' | 'offline' | 'unknown'
  seconds_since_last_seen: number | null
}

export type CreateDeviceIn = {
  device_id: string
  display_name?: string
  token: string
  heartbeat_interval_s?: number
  offline_after_s?: number
}

export type UpdateDeviceIn = {
  display_name?: string
  token?: string
  heartbeat_interval_s?: number
  offline_after_s?: number
  enabled?: boolean
}

export type DeviceSummaryOut = {
  device_id: string
  display_name: string
  heartbeat_interval_s: number
  offline_after_s: number
  last_seen_at: string | null
  enabled: boolean
  status: 'online' | 'offline' | 'unknown'
  seconds_since_last_seen: number | null
  latest_telemetry_at: string | null
  latest_message_id: string | null
  metrics: Record<string, unknown>
}

export type AlertOut = {
  id: string
  device_id: string
  alert_type: string
  severity: string
  message: string
  created_at: string
  resolved_at: string | null
}

export type TimeseriesPoint = {
  bucket_ts: string
  value: number
}

export type TimeseriesMultiPoint = {
  bucket_ts: string
  values: Record<string, number | null>
}

export type TelemetryContractMetric = {
  type: string
  unit?: string | null
  description?: string | null
}

export type TelemetryContract = {
  version: string
  sha256: string
  metrics: Record<string, TelemetryContractMetric>
}

export type EdgePolicyContractOut = {
  policy_version: string
  policy_sha256: string
  cache_max_age_s: number
  reporting: {
    sample_interval_s: number
    alert_sample_interval_s: number
    heartbeat_interval_s: number
    alert_report_interval_s: number

    max_points_per_batch: number
    buffer_max_points: number
    buffer_max_age_s: number

    backoff_initial_s: number
    backoff_max_s: number
  }
  delta_thresholds: Record<string, number>
  alert_thresholds: {
    water_pressure_low_psi: number
    water_pressure_recover_psi: number

    oil_pressure_low_psi: number
    oil_pressure_recover_psi: number

    oil_level_low_pct: number
    oil_level_recover_pct: number

    drip_oil_level_low_pct: number
    drip_oil_level_recover_pct: number

    oil_life_low_pct: number
    oil_life_recover_pct: number

    battery_low_v: number
    battery_recover_v: number

    signal_low_rssi_dbm: number
    signal_recover_rssi_dbm: number
  }
  cost_caps: {
    max_bytes_per_day: number
    max_snapshots_per_day: number
    max_media_uploads_per_day: number
  }
}

export type IngestionBatchOut = {
  id: string
  device_id: string
  received_at: string
  contract_version: string
  contract_hash: string
  points_submitted: number
  points_accepted: number
  duplicates: number
  points_quarantined: number
  client_ts_min: string | null
  client_ts_max: string | null
  unknown_metric_keys: string[]
  type_mismatch_keys: string[]
  drift_summary: Record<string, unknown>
  source: string
  pipeline_mode: string
  processing_status: string
}

export type DriftEventOut = {
  id: string
  batch_id: string
  device_id: string
  event_type: string
  action: string
  details: Record<string, unknown>
  created_at: string
}

export type NotificationEventOut = {
  id: string
  alert_id: string | null
  device_id: string
  alert_type: string
  channel: string
  decision: string
  delivered: boolean
  reason: string
  created_at: string
}

export type ExportBatchOut = {
  id: string
  started_at: string
  finished_at: string | null
  watermark_from: string | null
  watermark_to: string | null
  contract_version: string
  contract_hash: string
  gcs_uri: string | null
  row_count: number
  status: string
  error_message: string | null
}

export type MediaObjectOut = {
  id: string
  device_id: string
  camera_id: string
  message_id: string
  captured_at: string
  reason: string
  sha256: string
  bytes: number
  mime_type: string
  object_path: string
  gcs_uri: string | null
  local_path: string | null
  uploaded_at: string | null
  created_at: string
}

export type TelemetryPoint = {
  message_id: string
  device_id: string
  ts: string
  metrics: Record<string, unknown>
}

async function getJSON<T>(path: string, opts?: { headers?: Record<string, string> }): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts?.headers) {
    for (const [k, v] of Object.entries(opts.headers)) headers[k] = v
  }
  let res = await fetch(path, { headers })

  // If an intermediary returns a 304 (Not Modified), re-fetch bypassing caches
  // so callers always receive a JSON body.
  if (res.status === 304) {
    res = await fetch(path, { headers, cache: 'reload' })
  }
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${body ? ` - ${body}` : ''}`)
  }
  return res.json() as Promise<T>
}

async function sendJSON<T>(
  path: string,
  body: unknown,
  opts?: { method?: 'POST' | 'PATCH' | 'PUT' | 'DELETE'; headers?: Record<string, string> },
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
  }
  if (opts?.headers) {
    for (const [k, v] of Object.entries(opts.headers)) headers[k] = v
  }

  const res = await fetch(path, {
    method: opts?.method ?? 'POST',
    headers,
    body: JSON.stringify(body ?? {}),
  })

  if (!res.ok) {
    const txt = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${txt ? ` - ${txt}` : ''}`)
  }
  return res.json() as Promise<T>
}

async function getBlob(
  path: string,
  opts?: { headers?: Record<string, string>; cache?: RequestCache },
): Promise<Blob> {
  const headers: Record<string, string> = {}
  if (opts?.headers) {
    for (const [k, v] of Object.entries(opts.headers)) headers[k] = v
  }
  const res = await fetch(path, {
    headers,
    cache: opts?.cache ?? 'no-store',
  })

  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${body ? ` - ${body}` : ''}`)
  }
  return res.blob()
}

function adminHeaders(adminKey: string | null | undefined): Record<string, string> {
  const k = (adminKey ?? '').trim()
  return k ? { 'X-Admin-Key': k } : {}
}

function bearerHeaders(token: string | null | undefined): Record<string, string> {
  const t = (token ?? '').trim()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

export const api = {
  health: () =>
    getJSON<{
      ok: boolean
      env: string
      version?: string
      features?: {
        admin?: { enabled?: boolean; auth_mode?: string }
        docs?: { enabled?: boolean }
        otel?: { enabled?: boolean }
        ui?: { enabled?: boolean }
        routes?: { ingest?: boolean; read?: boolean }
        ingest?: { pipeline_mode?: string }
        analytics_export?: { enabled?: boolean }
        retention?: { enabled?: boolean }
        limits?: {
          max_request_body_bytes?: number
          max_points_per_request?: number
          rate_limit_enabled?: boolean
          ingest_rate_limit_points_per_min?: number
        }
      }
    }>('/api/v1/health'),
  devices: () => getJSON<DeviceOut[]>('/api/v1/devices'),
  devicesSummary: (opts?: { metrics?: string[] }) => {
    const params = new URLSearchParams()
    for (const m of opts?.metrics ?? []) params.append('metrics', m)
    const qs = params.toString()
    return getJSON<DeviceSummaryOut[]>(`/api/v1/devices/summary${qs ? `?${qs}` : ''}`)
  },
  device: (device_id: string) => getJSON<DeviceOut>(`/api/v1/devices/${encodeURIComponent(device_id)}`),
  alerts: (
    opts?: {
      limit?: number
      device_id?: string
      open_only?: boolean
      severity?: string
      alert_type?: string
      before?: string
      before_id?: string
    },
  ) => {
    const params = new URLSearchParams()
    params.set('limit', String(opts?.limit ?? 50))
    if (opts?.device_id) params.set('device_id', opts.device_id)
    if (opts?.open_only) params.set('open_only', 'true')
    if (opts?.severity) params.set('severity', opts.severity)
    if (opts?.alert_type) params.set('alert_type', opts.alert_type)
    if (opts?.before) params.set('before', opts.before)
    if (opts?.before_id) params.set('before_id', opts.before_id)
    return getJSON<AlertOut[]>(`/api/v1/alerts?${params.toString()}`)
  },
  telemetryContract: () => getJSON<TelemetryContract>('/api/v1/contracts/telemetry'),
  edgePolicyContract: () => getJSON<EdgePolicyContractOut>('/api/v1/contracts/edge_policy'),
  telemetry: (device_id: string, opts?: { metric?: string; since?: string; until?: string; limit?: number }) => {
    const params = new URLSearchParams()
    if (opts?.metric) params.set('metric', opts.metric)
    if (opts?.since) params.set('since', opts.since)
    if (opts?.until) params.set('until', opts.until)
    params.set('limit', String(opts?.limit ?? 200))
    return getJSON<TelemetryPoint[]>(
      `/api/v1/devices/${encodeURIComponent(device_id)}/telemetry?${params.toString()}`,
    )
  },
  timeseriesMulti: (
    device_id: string,
    metrics: string[],
    bucket: 'minute' | 'hour' = 'minute',
    opts?: { since?: string; until?: string; limit?: number },
  ) => {
    const params = new URLSearchParams()
    for (const m of metrics) params.append('metrics', m)
    params.set('bucket', bucket)
    if (opts?.since) params.set('since', opts.since)
    if (opts?.until) params.set('until', opts.until)
    if (opts?.limit) params.set('limit', String(opts.limit))
    return getJSON<TimeseriesMultiPoint[]>(
      `/api/v1/devices/${encodeURIComponent(device_id)}/timeseries_multi?${params.toString()}`,
    )
  },
  timeseries: (
    device_id: string,
    metric: string,
    bucket: 'minute' | 'hour' = 'minute',
    opts?: { since?: string; until?: string; limit?: number },
  ) => {
    const params = new URLSearchParams()
    params.set('metric', metric)
    params.set('bucket', bucket)
    if (opts?.since) params.set('since', opts.since)
    if (opts?.until) params.set('until', opts.until)
    if (opts?.limit) params.set('limit', String(opts.limit))
    return getJSON<TimeseriesPoint[]>(`/api/v1/devices/${encodeURIComponent(device_id)}/timeseries?${params.toString()}`)
  },
  latestTelemetry: (device_id: string) =>
    getJSON<TelemetryPoint[]>(
      `/api/v1/devices/${encodeURIComponent(device_id)}/telemetry?limit=1`,
    ).then((rows) => rows[0] ?? null),
  media: {
    list: (deviceId: string, opts: { token: string; limit?: number }) => {
      const params = new URLSearchParams()
      params.set('limit', String(opts.limit ?? 200))
      return getJSON<MediaObjectOut[]>(
        `/api/v1/devices/${encodeURIComponent(deviceId)}/media?${params.toString()}`,
        { headers: bearerHeaders(opts.token) },
      )
    },
    downloadPath: (mediaId: string) => `/api/v1/media/${encodeURIComponent(mediaId)}/download`,
    downloadBlob: (mediaId: string, token: string) =>
      getBlob(`/api/v1/media/${encodeURIComponent(mediaId)}/download`, {
        headers: bearerHeaders(token),
        cache: 'no-store',
      }),
  },

  admin: {
    devices: (adminKey: string) => getJSON<DeviceOut[]>('/api/v1/admin/devices', { headers: adminHeaders(adminKey) }),
    createDevice: (adminKey: string | null | undefined, payload: CreateDeviceIn) =>
      sendJSON<DeviceOut>('/api/v1/admin/devices', payload, { method: 'POST', headers: adminHeaders(adminKey) }),
    updateDevice: (adminKey: string | null | undefined, deviceId: string, payload: UpdateDeviceIn) =>
      sendJSON<DeviceOut>(`/api/v1/admin/devices/${encodeURIComponent(deviceId)}`, payload, {
        method: 'PATCH',
        headers: adminHeaders(adminKey),
      }),
    ingestions: (adminKey: string, opts?: { device_id?: string; limit?: number }) => {
      const params = new URLSearchParams()
      if (opts?.device_id) params.set('device_id', opts.device_id)
      params.set('limit', String(opts?.limit ?? 200))
      return getJSON<IngestionBatchOut[]>(`/api/v1/admin/ingestions?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    driftEvents: (adminKey: string, opts?: { device_id?: string; limit?: number }) => {
      const params = new URLSearchParams()
      if (opts?.device_id) params.set('device_id', opts.device_id)
      params.set('limit', String(opts?.limit ?? 200))
      return getJSON<DriftEventOut[]>(`/api/v1/admin/drift-events?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    notifications: (adminKey: string, opts?: { device_id?: string; limit?: number }) => {
      const params = new URLSearchParams()
      if (opts?.device_id) params.set('device_id', opts.device_id)
      params.set('limit', String(opts?.limit ?? 200))
      return getJSON<NotificationEventOut[]>(`/api/v1/admin/notifications?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    exports: (adminKey: string, opts?: { status?: string; limit?: number }) => {
      const params = new URLSearchParams()
      if (opts?.status) params.set('status_filter', opts.status)
      params.set('limit', String(opts?.limit ?? 200))
      return getJSON<ExportBatchOut[]>(`/api/v1/admin/exports?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
  },
}
