import * as React from 'react'
import { Link } from '@tanstack/react-router'
import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { AlertOut, DeviceSummaryOut } from '../api'
import { Badge, Button } from '../ui-kit'
import { fmtDateTime } from '../utils/format'

type MappedDevice = {
  device: DeviceSummaryOut
  lat: number
  lon: number
  source: 'telemetry' | 'fallback'
}

type FleetMapProps = {
  devices: DeviceSummaryOut[]
  openAlerts: AlertOut[]
}

const MAP_DEFAULT_CENTER: [number, number] = [39.5, -98.35]
const MAP_DEFAULT_ZOOM = 4
const DEMO_CENTER: [number, number] = [37.4083, -102.6144]
const DEMO_RADIUS_MI = 50
const EARTH_RADIUS_MI = 3958.7613

const LOCATION_KEY_PAIRS: readonly (readonly [string, string])[] = [
  ['latitude', 'longitude'],
  ['lat', 'lon'],
  ['lat', 'lng'],
  ['gps_latitude', 'gps_longitude'],
  ['location_lat', 'location_lon'],
]

function parseCoordinate(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number.parseFloat(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function isValidLatLon(lat: number, lon: number): boolean {
  return Number.isFinite(lat) && Number.isFinite(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180
}

function extractTelemetryLocation(metrics: Record<string, unknown>): { lat: number; lon: number } | null {
  for (const [latKey, lonKey] of LOCATION_KEY_PAIRS) {
    const lat = parseCoordinate(metrics[latKey])
    const lon = parseCoordinate(metrics[lonKey])
    if (lat == null || lon == null) continue
    if (isValidLatLon(lat, lon)) {
      return { lat, lon }
    }
  }
  return null
}

function hash32(input: string): number {
  let hash = 0
  for (let i = 0; i < input.length; i += 1) {
    hash = ((hash << 5) - hash + input.charCodeAt(i)) | 0
  }
  return hash >>> 0
}

function normalizeLon(lonDeg: number): number {
  return ((lonDeg + 180) % 360) - 180
}

function demoFallbackLocation(deviceId: string): { lat: number; lon: number } {
  const distanceHash = hash32(`${deviceId}:distance`)
  const bearingHash = hash32(`${deviceId}:bearing`)
  const u = distanceHash / 0xffffffff
  const v = bearingHash / 0xffffffff
  const distanceMi = DEMO_RADIUS_MI * Math.sqrt(u)
  const bearingRad = 2 * Math.PI * v

  const lat1Rad = (DEMO_CENTER[0] * Math.PI) / 180
  const lon1Rad = (DEMO_CENTER[1] * Math.PI) / 180
  const angularDistance = distanceMi / EARTH_RADIUS_MI

  const lat2Rad = Math.asin(
    Math.sin(lat1Rad) * Math.cos(angularDistance)
      + Math.cos(lat1Rad) * Math.sin(angularDistance) * Math.cos(bearingRad),
  )
  const lon2Rad =
    lon1Rad +
    Math.atan2(
      Math.sin(bearingRad) * Math.sin(angularDistance) * Math.cos(lat1Rad),
      Math.cos(angularDistance) - Math.sin(lat1Rad) * Math.sin(lat2Rad),
    )

  return {
    lat: Number(((lat2Rad * 180) / Math.PI).toFixed(6)),
    lon: Number(normalizeLon((lon2Rad * 180) / Math.PI).toFixed(6)),
  }
}

function statusVariant(status: DeviceSummaryOut['status']): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (status === 'online') return 'success'
  if (status === 'offline') return 'destructive'
  if (status === 'sleep') return 'warning'
  return 'secondary'
}

function markerStyle(status: DeviceSummaryOut['status']): L.CircleMarkerOptions {
  if (status === 'online') {
    return { radius: 8, color: '#065f46', weight: 2, fillColor: '#10b981', fillOpacity: 0.95 }
  }
  if (status === 'offline') {
    return { radius: 8, color: '#7f1d1d', weight: 2, fillColor: '#ef4444', fillOpacity: 0.95 }
  }
  if (status === 'sleep') {
    return { radius: 8, color: '#854d0e', weight: 2, fillColor: '#f59e0b', fillOpacity: 0.95 }
  }
  if (status === 'disabled') {
    return { radius: 8, color: '#334155', weight: 2, fillColor: '#64748b', fillOpacity: 0.95 }
  }
  return { radius: 8, color: '#334155', weight: 2, fillColor: '#94a3b8', fillOpacity: 0.95 }
}

export function FleetMap(props: FleetMapProps) {
  const mapContainerRef = React.useRef<HTMLDivElement | null>(null)
  const mapRef = React.useRef<L.Map | null>(null)
  const markersRef = React.useRef<L.LayerGroup | null>(null)
  const hasFitBoundsRef = React.useRef(false)
  const [selectedDeviceId, setSelectedDeviceId] = React.useState<string | null>(null)

  const openAlertCountByDevice = React.useMemo(() => {
    const counts = new Map<string, number>()
    for (const alert of props.openAlerts) {
      counts.set(alert.device_id, (counts.get(alert.device_id) ?? 0) + 1)
    }
    return counts
  }, [props.openAlerts])

  const mappedDevices = React.useMemo<MappedDevice[]>(() => {
    const out: MappedDevice[] = []
    for (const device of props.devices) {
      const telemetry = extractTelemetryLocation(device.metrics ?? {})
      if (telemetry) {
        out.push({ device, lat: telemetry.lat, lon: telemetry.lon, source: 'telemetry' })
        continue
      }
      const fallback = demoFallbackLocation(device.device_id)
      out.push({ device, lat: fallback.lat, lon: fallback.lon, source: 'fallback' })
    }
    return out
  }, [props.devices])

  const telemetryLocationCount = React.useMemo(
    () => mappedDevices.filter((device) => device.source === 'telemetry').length,
    [mappedDevices],
  )
  const fallbackLocationCount = mappedDevices.length - telemetryLocationCount

  const selectedDevice = React.useMemo(() => {
    if (!mappedDevices.length) return null
    if (!selectedDeviceId) return mappedDevices[0]
    return mappedDevices.find((d) => d.device.device_id === selectedDeviceId) ?? mappedDevices[0]
  }, [mappedDevices, selectedDeviceId])

  const recenter = React.useCallback(() => {
    const map = mapRef.current
    if (!map || !mappedDevices.length) return
    const bounds = L.latLngBounds(mappedDevices.map((d) => [d.lat, d.lon] as [number, number]))
    map.fitBounds(bounds.pad(0.28), { maxZoom: 12 })
    hasFitBoundsRef.current = true
  }, [mappedDevices])

  React.useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return
    const map = L.map(mapContainerRef.current, {
      center: MAP_DEFAULT_CENTER,
      zoom: MAP_DEFAULT_ZOOM,
      scrollWheelZoom: true,
      zoomControl: true,
    })
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 19,
    }).addTo(map)
    mapRef.current = map
    requestAnimationFrame(() => {
      map.invalidateSize()
    })
    return () => {
      map.remove()
      mapRef.current = null
      markersRef.current = null
      hasFitBoundsRef.current = false
    }
  }, [])

  React.useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (markersRef.current) {
      markersRef.current.remove()
      markersRef.current = null
    }

    const layer = L.layerGroup()
    for (const item of mappedDevices) {
      const label = item.device.display_name || item.device.device_id
      const marker = L.circleMarker([item.lat, item.lon], markerStyle(item.device.status))
      marker.bindTooltip(`${label} · ${item.device.status}`, { direction: 'top', offset: [0, -8], opacity: 0.9 })
      marker.on('click', () => {
        setSelectedDeviceId(item.device.device_id)
      })
      marker.addTo(layer)
    }

    layer.addTo(map)
    markersRef.current = layer

    if (!mappedDevices.length) {
      map.setView(MAP_DEFAULT_CENTER, MAP_DEFAULT_ZOOM)
      hasFitBoundsRef.current = false
      return
    }

    if (!hasFitBoundsRef.current) {
      const bounds = L.latLngBounds(mappedDevices.map((d) => [d.lat, d.lon] as [number, number]))
      map.fitBounds(bounds.pad(0.28), { maxZoom: 12 })
      hasFitBoundsRef.current = true
    }
  }, [mappedDevices])

  React.useEffect(() => {
    if (!mappedDevices.length) {
      if (selectedDeviceId !== null) setSelectedDeviceId(null)
      return
    }
    if (selectedDeviceId && mappedDevices.some((d) => d.device.device_id === selectedDeviceId)) {
      return
    }
    setSelectedDeviceId(mappedDevices[0].device.device_id)
  }, [mappedDevices, selectedDeviceId])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">mapped: {mappedDevices.length}/{props.devices.length}</Badge>
        <Badge variant="secondary">telemetry coords: {telemetryLocationCount}</Badge>
        {fallbackLocationCount > 0 ? <Badge variant="warning">fallback: {fallbackLocationCount}</Badge> : null}
        <Button variant="outline" size="sm" onClick={recenter} disabled={!mappedDevices.length} className="ml-auto">
          Recenter
        </Button>
      </div>

      <div ref={mapContainerRef} className="h-[420px] w-full overflow-hidden rounded-md border" />

      {!mappedDevices.length ? (
        <div className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
          No mappable device locations yet. Provide location metrics in telemetry using keys like{' '}
          <span className="font-mono">latitude/longitude</span>, <span className="font-mono">lat/lon</span>, or{' '}
          <span className="font-mono">gps_latitude/gps_longitude</span>.
        </div>
      ) : null}

      {selectedDevice ? (
        <div className="grid gap-3 rounded-md border bg-muted/20 p-3 md:grid-cols-2">
          <div className="space-y-2">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">Selected device</div>
            <div className="flex flex-wrap items-center gap-2">
              <Link
                to="/devices/$deviceId"
                params={{ deviceId: selectedDevice.device.device_id }}
                className="font-mono text-xs"
              >
                {selectedDevice.device.device_id}
              </Link>
              <Badge variant={statusVariant(selectedDevice.device.status)}>{selectedDevice.device.status}</Badge>
              <Badge variant={selectedDevice.source === 'telemetry' ? 'secondary' : 'warning'}>
                {selectedDevice.source === 'telemetry' ? 'telemetry location' : 'fallback location'}
              </Badge>
            </div>
            <div className="text-sm text-muted-foreground">
              {selectedDevice.device.display_name || 'No display name'}
            </div>
            <div className="font-mono text-xs text-muted-foreground">
              lat {selectedDevice.lat.toFixed(5)} · lon {selectedDevice.lon.toFixed(5)}
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">Status details</div>
            <div className="text-sm text-muted-foreground">
              Last seen: {fmtDateTime(selectedDevice.device.last_seen_at)}
            </div>
            <div className="text-sm text-muted-foreground">
              Latest telemetry: {fmtDateTime(selectedDevice.device.latest_telemetry_at)}
            </div>
            <div className="flex items-center gap-2">
              <Badge variant={(openAlertCountByDevice.get(selectedDevice.device.device_id) ?? 0) > 0 ? 'destructive' : 'secondary'}>
                open alerts: {openAlertCountByDevice.get(selectedDevice.device.device_id) ?? 0}
              </Badge>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
