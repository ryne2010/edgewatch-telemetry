import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearch } from '@tanstack/react-router'
import { api } from '../api'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Page } from '../ui-kit'
import { buildAlertsSearch, buildHref } from '../utils/filterUrlState'

type StreamRow = {
  type: string
  id: string
  device_id?: string
  event_type?: string
  created_at?: string
  body?: Record<string, unknown>
}

function eventLink(sourceKind: string, row: { device_id?: string | null; event_name?: string; payload?: Record<string, unknown> }) {
  if (sourceKind === 'alert') {
    const rawSeverity = typeof row.payload?.severity === 'string' ? row.payload.severity.toLowerCase() : ''
    const severity =
      rawSeverity === 'critical' || rawSeverity === 'warning' || rawSeverity === 'info' ? rawSeverity : 'all'
    const href = buildHref(
      '/alerts',
      buildAlertsSearch({
        resolutionFilter: 'all',
        severityFilter: severity,
        typeFilter: row.event_name ?? 'all',
        deviceFilter: row.device_id ?? '',
        search: '',
        limit: 200,
      }),
    )
    return (
      <a href={`${href}#alerts-feed`} className="underline text-xs">
        alerts
      </a>
    )
  }
  if (sourceKind === 'notification_event') {
    const params = new URLSearchParams({
      tab: 'notifications',
      deviceId: row.device_id ?? '',
      batchId: '',
      status: '',
      exportId: '',
      action: '',
      targetType: '',
      sourceKind: '',
      channel: '',
      decision: '',
      delivered: '',
      procedureName: '',
    })
    const href = `${buildHref('/admin', params.toString())}#admin-notifications`
    return (
      <a href={href} className="underline text-xs">
        admin
      </a>
    )
  }
  if (sourceKind === 'deployment_event') {
    const params = new URLSearchParams({
      deploymentId: String(row.payload?.deployment_id ?? ''),
      manifestId: '',
      targetDeviceId: row.device_id ?? '',
    })
    const href = `${buildHref('/releases', params.toString())}#releases-deployment-inspector`
    return (
      <a href={href} className="underline text-xs">
        releases
      </a>
    )
  }
  if (sourceKind === 'release_manifest_event') {
    const params = new URLSearchParams({
      deploymentId: '',
      manifestId: String(row.payload?.manifest_id ?? ''),
      targetDeviceId: '',
    })
    const href = `${buildHref('/releases', params.toString())}#releases-manifests`
    return (
      <a href={href} className="underline text-xs">
        releases
      </a>
    )
  }
  if (sourceKind === 'admin_event') {
    const params = new URLSearchParams({
      tab: 'events',
      deviceId: row.payload?.target_device_id ? String(row.payload.target_device_id) : '',
      batchId: '',
      status: '',
      exportId: '',
      action: '',
      targetType: '',
      sourceKind: '',
      channel: '',
      decision: '',
      delivered: '',
      procedureName: '',
    })
    const href = `${buildHref('/admin', params.toString())}#admin-events`
    return (
      <a href={href} className="underline text-xs">
        admin
      </a>
    )
  }
  if (sourceKind === 'device_event' || sourceKind === 'procedure_invocation') {
    const href = `/devices/${encodeURIComponent(row.device_id ?? '')}?tab=${sourceKind === 'device_event' ? 'events' : 'procedures'}#${sourceKind === 'device_event' ? 'device-events' : 'device-procedures'}`
    return (
      <a href={href} className="underline text-xs">
        live
      </a>
    )
  }
  return null
}

export function LivePage() {
  const routeSearch = useSearch({ from: '/live' })
  const [deviceId, setDeviceId] = React.useState('')
  const [sourceKindsInput, setSourceKindsInput] = React.useState('alert,notification_event,device_event,procedure_invocation,deployment_event,release_manifest_event,admin_event')
  const [eventNameInput, setEventNameInput] = React.useState('')
  const [sinceSecondsInput, setSinceSecondsInput] = React.useState('300')
  const [rows, setRows] = React.useState<StreamRow[]>([])
  const [connected, setConnected] = React.useState(false)
  const [historyOffset, setHistoryOffset] = React.useState(0)
  const historyLimit = 25
  const typeCounts = React.useMemo(() => {
    return rows.reduce<Record<string, number>>((acc, row) => {
      acc[row.type] = (acc[row.type] ?? 0) + 1
      return acc
    }, {})
  }, [rows])

  const historyQ = useQuery({
    queryKey: ['operatorEvents', deviceId.trim(), sourceKindsInput.trim(), eventNameInput.trim(), sinceSecondsInput, historyOffset],
    queryFn: () =>
      api.operatorEvents({
        limit: historyLimit,
        offset: historyOffset,
        device_id: deviceId.trim() || undefined,
        event_name: eventNameInput.trim() || undefined,
        sourceKinds: sourceKindsInput
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean) as Array<'alert' | 'notification_event' | 'device_event' | 'procedure_invocation' | 'deployment_event' | 'release_manifest_event' | 'admin_event'>,
      }),
    refetchInterval: 15_000,
  })

  React.useEffect(() => {
    setHistoryOffset(0)
  }, [deviceId, eventNameInput, sourceKindsInput])

  React.useEffect(() => {
    if (routeSearch.deviceId) setDeviceId(routeSearch.deviceId)
    if (routeSearch.sourceKinds) setSourceKindsInput(routeSearch.sourceKinds)
    if (routeSearch.eventName) setEventNameInput(routeSearch.eventName)
    if (routeSearch.sinceSeconds) setSinceSecondsInput(routeSearch.sinceSeconds)
  }, [routeSearch.deviceId, routeSearch.eventName, routeSearch.sinceSeconds, routeSearch.sourceKinds])

  React.useEffect(() => {
    const params = new URLSearchParams()
    if (deviceId.trim()) params.set('device_id', deviceId.trim())
    if (eventNameInput.trim()) params.set('event_name', eventNameInput.trim())
    const sinceSeconds = Number.parseInt(sinceSecondsInput, 10)
    if (Number.isFinite(sinceSeconds) && sinceSeconds > 0) params.set('since_seconds', String(sinceSeconds))
    for (const sourceKind of sourceKindsInput.split(',').map((v) => v.trim()).filter(Boolean)) {
      params.append('source_kind', sourceKind)
    }
    const url = `/api/v1/event-stream${params.toString() ? `?${params.toString()}` : ''}`
    const source = new EventSource(url)
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)
    const handler = (evt: MessageEvent<string>) => {
      try {
        const parsed = JSON.parse(evt.data) as StreamRow
        setRows((prev) => [parsed, ...prev].slice(0, 100))
      } catch {
        // ignore malformed keepalive/data frames
      }
    }
    source.addEventListener('alert', handler as EventListener)
    source.addEventListener('notification_event', handler as EventListener)
    source.addEventListener('device_event', handler as EventListener)
    source.addEventListener('procedure_invocation', handler as EventListener)
    source.addEventListener('deployment_event', handler as EventListener)
    source.addEventListener('release_manifest_event', handler as EventListener)
    source.addEventListener('admin_event', handler as EventListener)
    return () => {
      source.close()
      setConnected(false)
    }
  }, [deviceId, eventNameInput, sinceSecondsInput, sourceKindsInput])

  return (
    <Page
      title="Live"
      description="Live operator event stream across alerts, device events, and procedures."
      actions={
        <div className="flex items-center gap-2">
          {connected ? <Badge variant="success">connected</Badge> : <Badge variant="warning">disconnected</Badge>}
          <Badge variant="outline">rows: {rows.length}</Badge>
          {Object.entries(typeCounts).map(([type, count]) => (
            <Badge key={type} variant="secondary">
              {type}: {count}
            </Badge>
          ))}
        </div>
      }
    >
      <Card>
        <CardHeader>
          <CardTitle>Event stream</CardTitle>
          <CardDescription>Uses the backend SSE stream. Filter to one device or leave blank for everything you can see.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 lg:grid-cols-2">
            <div className="flex gap-2">
              <Input value={deviceId} onChange={(e) => setDeviceId(e.target.value)} placeholder="Optional device id filter…" />
              <Button
                variant="outline"
                onClick={() => {
                  setDeviceId('')
                  setEventNameInput('')
                  setSinceSecondsInput('300')
                  setSourceKindsInput('alert,notification_event,device_event,procedure_invocation,deployment_event,release_manifest_event,admin_event')
                }}
              >
                Reset
              </Button>
            </div>
            <Input
              value={sourceKindsInput}
              onChange={(e) => setSourceKindsInput(e.target.value)}
              placeholder="alert,notification_event,device_event,procedure_invocation,deployment_event,release_manifest_event,admin_event"
            />
          </div>
          <Input
            value={eventNameInput}
            onChange={(e) => setEventNameInput(e.target.value)}
            placeholder="Optional event name filter (for example BATTERY_LOW or capture_snapshot)…"
          />
          <Input
            value={sinceSecondsInput}
            onChange={(e) => setSinceSecondsInput(e.target.value)}
            placeholder="Replay window in seconds (for example 300)"
          />
          <div className="text-xs text-muted-foreground">
            Source kinds are comma-separated values from <code className="font-mono">alert</code>, <code className="font-mono">notification_event</code>, <code className="font-mono">device_event</code>, <code className="font-mono">procedure_invocation</code>, <code className="font-mono">deployment_event</code>, <code className="font-mono">release_manifest_event</code>, and <code className="font-mono">admin_event</code>. Event name filtering and the recent replay window are applied server-side.
          </div>
          <div className="rounded-md border bg-muted/20 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-medium">Recent history</div>
              {historyQ.data ? (
                <div className="text-xs text-muted-foreground">
                  Showing {Math.min(historyQ.data.total, historyOffset + 1)}-{Math.min(historyQ.data.total, historyOffset + historyQ.data.items.length)} of {historyQ.data.total}
                </div>
              ) : null}
            </div>
            {historyQ.isLoading ? <div className="mt-2 text-sm text-muted-foreground">Loading recent events…</div> : null}
            {historyQ.isError ? <div className="mt-2 text-sm text-destructive">Error: {(historyQ.error as Error).message}</div> : null}
            {(historyQ.data?.items.length ?? 0) > 0 ? (
              <div className="mt-3 space-y-2">
                {historyQ.data?.items.map((row) => (
                  <div key={`${row.source_kind}:${row.entity_id}`} className="rounded-md border bg-background p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">{row.source_kind}</Badge>
                      <div className="font-medium">{row.event_name}</div>
                      {row.device_id ? <div className="font-mono text-xs text-muted-foreground">{row.device_id}</div> : null}
                      {eventLink(row.source_kind, row)}
                      <div className="ml-auto text-xs text-muted-foreground">{new Date(row.created_at).toLocaleString()}</div>
                    </div>
                  </div>
                ))}
                <div className="flex items-center gap-2">
                  <Button variant="outline" onClick={() => setHistoryOffset((current) => Math.max(0, current - historyLimit))} disabled={historyOffset <= 0}>
                    Previous page
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => setHistoryOffset((current) => current + historyLimit)}
                    disabled={(historyQ.data?.offset ?? 0) + (historyQ.data?.limit ?? historyLimit) >= (historyQ.data?.total ?? 0)}
                  >
                    Next page
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
          <div className="space-y-2">
            {rows.length === 0 ? <div className="text-sm text-muted-foreground">Waiting for events…</div> : null}
            {rows.map((row, idx) => (
              <div key={`${row.type}:${row.id}:${idx}`} className="rounded-md border bg-background p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">{row.type}</Badge>
                  {row.event_type ? <div className="font-medium">{row.event_type}</div> : null}
                  {row.device_id ? <div className="font-mono text-xs text-muted-foreground">{row.device_id}</div> : null}
                  {eventLink(row.type, { device_id: row.device_id, event_name: row.event_type, payload: row.body })}
                  {row.device_id ? (
                    <Link to="/devices/$deviceId" params={{ deviceId: row.device_id }} className="underline text-xs">
                      device
                    </Link>
                  ) : null}
                  {row.created_at ? <div className="ml-auto text-xs text-muted-foreground">{new Date(row.created_at).toLocaleString()}</div> : null}
                </div>
                {row.body ? (
                  <details className="mt-2 text-xs text-muted-foreground">
                    <summary className="cursor-pointer">payload</summary>
                    <pre className="mt-2 whitespace-pre-wrap break-words">{JSON.stringify(row.body, null, 2)}</pre>
                  </details>
                ) : null}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </Page>
  )
}
