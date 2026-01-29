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

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { 'Accept': 'application/json' } })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${body ? ` - ${body}` : ''}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => getJSON<{ ok: boolean; env: string }>('/api/v1/health'),
  devices: () => getJSON<DeviceOut[]>('/api/v1/devices'),
  device: (device_id: string) => getJSON<DeviceOut>(`/api/v1/devices/${encodeURIComponent(device_id)}`),
  alerts: (limit: number = 50) => getJSON<AlertOut[]>(`/api/v1/alerts?limit=${limit}`),
  timeseries: (device_id: string, metric: string, bucket: 'minute' | 'hour' = 'minute') =>
    getJSON<TimeseriesPoint[]>(
      `/api/v1/devices/${encodeURIComponent(device_id)}/timeseries?metric=${encodeURIComponent(metric)}&bucket=${bucket}`,
    ),
}
