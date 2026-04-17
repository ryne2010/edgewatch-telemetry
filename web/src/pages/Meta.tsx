import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api } from '../api'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Page, Separator } from '../ui-kit'
import { buildAlertsSearch, buildHref } from '../utils/filterUrlState'

function KeyValue(props: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b py-2 last:border-b-0">
      <div className="text-sm text-muted-foreground">{props.k}</div>
      <div className="text-sm font-medium">{props.v}</div>
    </div>
  )
}

export function MetaPage() {
  const [search, setSearch] = React.useState('')
  const [entityTypesInput, setEntityTypesInput] = React.useState('device,fleet,alert,ingestion_batch,drift_event,device_state,device_event,media_object,procedure_definition,procedure_invocation,deployment,deployment_event,release_manifest,release_manifest_event,admin_event,notification_event,notification_destination,device_access_grant,fleet_access_grant,export_batch')
  const [searchOffset, setSearchOffset] = React.useState(0)
  const searchLimit = 25
  const healthQ = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 60_000 })
  const telemetryContractQ = useQuery({ queryKey: ['telemetryContract'], queryFn: api.telemetryContract, staleTime: 5 * 60_000 })
  const edgePolicyQ = useQuery({ queryKey: ['edgePolicyContract'], queryFn: api.edgePolicyContract, staleTime: 5 * 60_000 })
  const searchQ = useQuery({
    queryKey: ['operatorSearch', search.trim(), entityTypesInput.trim(), searchOffset],
    queryFn: () =>
      api.searchPage(search.trim(), {
        limit: searchLimit,
        offset: searchOffset,
        entityTypes: entityTypesInput
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean) as Array<'device' | 'fleet' | 'alert' | 'ingestion_batch' | 'drift_event' | 'device_state' | 'device_event' | 'media_object' | 'procedure_definition' | 'procedure_invocation' | 'deployment' | 'deployment_event' | 'release_manifest' | 'release_manifest_event' | 'admin_event' | 'notification_event' | 'notification_destination' | 'device_access_grant' | 'fleet_access_grant' | 'export_batch'>,
      }),
    enabled: search.trim().length > 0,
  })

  React.useEffect(() => {
    setSearchOffset(0)
  }, [search, entityTypesInput])

  const env = healthQ.data?.env
  const version = healthQ.data?.version

  const searchLink = React.useCallback((row: {
    entity_type: string
    entity_id: string
    device_id: string | null
    title: string
    subtitle: string | null
    metadata?: Record<string, unknown>
  }) => {
    if (row.entity_type === 'device' && row.device_id) {
      return (
        <Link to="/devices/$deviceId" params={{ deviceId: row.device_id }} className="underline">
          open
        </Link>
      )
    }
    if (row.entity_type === 'fleet') {
      const params = new URLSearchParams({ fleetId: row.entity_id })
      const href = `${buildHref('/fleets', params.toString())}#fleet-devices`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'alert') {
      const href = buildHref(
        '/alerts',
        buildAlertsSearch({
          resolutionFilter: 'all',
          severityFilter: typeof row.metadata?.severity === 'string' ? (row.metadata.severity.toLowerCase() === 'critical' || row.metadata.severity.toLowerCase() === 'warning' || row.metadata.severity.toLowerCase() === 'info' ? (row.metadata.severity.toLowerCase() as 'critical' | 'warning' | 'info') : 'all') : 'all',
          typeFilter: row.title,
          deviceFilter: row.device_id ?? '',
          search: '',
          limit: 200,
        }),
      )
      return (
        <a href={`${href}#alerts-feed`} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'ingestion_batch') {
      const params = new URLSearchParams({
        tab: 'ingestions',
        deviceId: row.device_id ?? '',
        batchId: row.entity_id,
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
      const href = `${buildHref('/admin', params.toString())}#admin-ingestions`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'drift_event') {
      const params = new URLSearchParams({
        tab: 'drift',
        deviceId: row.device_id ?? '',
        batchId: typeof row.metadata?.batch_id === 'string' ? row.metadata.batch_id : '',
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
      const href = `${buildHref('/admin', params.toString())}#admin-drift`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'procedure_definition') {
      const params = new URLSearchParams({
        tab: '',
        deviceId: '',
        batchId: '',
        status: '',
        exportId: '',
        action: '',
        targetType: '',
        sourceKind: '',
        channel: '',
        decision: '',
        delivered: '',
        procedureName: row.title,
      })
      const href = `${buildHref('/admin', params.toString())}#procedure-definitions`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'device_state') {
      const href = `/devices/${encodeURIComponent(row.device_id ?? '')}?tab=state&stateKey=${encodeURIComponent(row.title)}#device-state`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'deployment') {
      const params = new URLSearchParams({
        deploymentId: row.entity_id,
        manifestId: '',
        targetDeviceId: row.device_id ?? '',
      })
      const href = `${buildHref('/releases', params.toString())}#releases-deployment-inspector`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'deployment_event') {
      const params = new URLSearchParams({
        deploymentId: typeof row.metadata?.deployment_id === 'string' ? row.metadata.deployment_id : row.subtitle ?? '',
        manifestId: '',
        targetDeviceId: row.device_id ?? '',
      })
      const href = `${buildHref('/releases', params.toString())}#releases-deployment-inspector`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'release_manifest') {
      const params = new URLSearchParams({
        deploymentId: '',
        manifestId: row.entity_id,
        targetDeviceId: '',
      })
      const href = `${buildHref('/releases', params.toString())}#releases-manifests`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'release_manifest_event') {
      const params = new URLSearchParams({
        deploymentId: '',
        manifestId: typeof row.metadata?.manifest_id === 'string' ? row.metadata.manifest_id : '',
        targetDeviceId: '',
      })
      const href = `${buildHref('/releases', params.toString())}#releases-manifests`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'admin_event') {
      const params = new URLSearchParams({
        tab: 'events',
        deviceId: row.device_id ?? '',
        batchId: '',
        status: '',
        exportId: '',
        action: row.title,
        targetType: row.subtitle ?? '',
        sourceKind: '',
        channel: '',
        decision: '',
        delivered: '',
        procedureName: '',
      })
      const href = `${buildHref('/admin', params.toString())}#admin-events`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'notification_event') {
      const params = new URLSearchParams({
        tab: 'notifications',
        deviceId: row.device_id ?? '',
        batchId: '',
        status: '',
        exportId: '',
        action: '',
        targetType: '',
        sourceKind: typeof row.metadata?.source_kind === 'string' ? row.metadata.source_kind : '',
        channel: typeof row.metadata?.channel === 'string' ? row.metadata.channel : '',
        decision: typeof row.metadata?.decision === 'string' ? row.metadata.decision : '',
        delivered: typeof row.metadata?.delivered === 'boolean' ? String(row.metadata.delivered) : '',
        procedureName: '',
      })
      const href = `${buildHref('/admin', params.toString())}#admin-notifications`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'notification_destination') {
      const href = `/settings?destinationId=${encodeURIComponent(row.entity_id)}#notification-webhooks`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'device_access_grant') {
      const params = new URLSearchParams({
        tab: '',
        deviceId: '',
        batchId: '',
        accessDeviceId: row.device_id ?? '',
        fleetId: '',
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
      const href = `${buildHref('/admin', params.toString())}#device-access`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'fleet_access_grant') {
      const params = new URLSearchParams({
        tab: '',
        deviceId: '',
        batchId: '',
        accessDeviceId: '',
        fleetId: typeof row.metadata?.fleet_id === 'string' ? row.metadata.fleet_id : '',
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
      const href = `${buildHref('/admin', params.toString())}#fleet-governance`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'export_batch') {
      const params = new URLSearchParams({
        tab: 'exports',
        deviceId: '',
        batchId: '',
        status: row.title,
        exportId: row.entity_id,
        action: '',
        targetType: '',
        sourceKind: '',
        channel: '',
        decision: '',
        delivered: '',
        procedureName: '',
      })
      const href = `${buildHref('/admin', params.toString())}#admin-exports`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'device_event') {
      const href = `/devices/${encodeURIComponent(row.device_id ?? '')}?tab=events#device-events`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'media_object') {
      const href = `/devices/${encodeURIComponent(row.device_id ?? '')}?tab=media&mediaCamera=${encodeURIComponent(row.title)}#device-media`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    if (row.entity_type === 'procedure_invocation') {
      const href = `/devices/${encodeURIComponent(row.device_id ?? '')}?tab=procedures#device-procedures`
      return (
        <a href={href} className="underline">
          open
        </a>
      )
    }
    return (
      <Link to="/live" search={{ deviceId: '', sourceKinds: '', eventName: '', sinceSeconds: '' }} className="underline">
        open
      </Link>
    )
  }, [])

  return (
    <Page
      title="System"
      description="Build/runtime metadata, contracts, and quick links."
      actions={
        <div className="flex items-center gap-2">
          {env ? <Badge variant="outline">env: {env}</Badge> : null}
          {version ? <Badge variant="secondary">v{version}</Badge> : null}
        </div>
      }
    >
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>API health</CardTitle>
            <CardDescription>
              Served from <code className="font-mono">/api/v1/health</code>.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {healthQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
            {healthQ.isError ? <div className="text-sm text-destructive">Error: {(healthQ.error as Error).message}</div> : null}
            {healthQ.data ? (
              <div className="mt-2">
                <KeyValue
                  k="OK"
                  v={healthQ.data.ok ? <Badge variant="success">true</Badge> : <Badge variant="destructive">false</Badge>}
                />
                <KeyValue k="Environment" v={<span className="font-mono text-xs">{healthQ.data.env}</span>} />
                <KeyValue
                  k="Version"
                  v={healthQ.data.version ? <span className="font-mono text-xs">{healthQ.data.version}</span> : '—'}
                />

                <Separator className="my-4" />

                <div className="text-sm font-medium">Feature flags</div>
                <div className="mt-2">
                  <KeyValue
                    k="UI"
                    v={
                      healthQ.data.features?.ui?.enabled ? (
                        <Badge variant="success">enabled</Badge>
                      ) : (
                        <Badge variant="secondary">disabled</Badge>
                      )
                    }
                  />
                  <KeyValue
                    k="Docs"
                    v={
                      healthQ.data.features?.docs?.enabled ? (
                        <Badge variant="success">enabled</Badge>
                      ) : (
                        <Badge variant="secondary">disabled</Badge>
                      )
                    }
                  />
                  <KeyValue
                    k="OpenTelemetry"
                    v={
                      healthQ.data.features?.otel?.enabled ? (
                        <Badge variant="success">enabled</Badge>
                      ) : (
                        <Badge variant="secondary">disabled</Badge>
                      )
                    }
                  />
                  <KeyValue
                    k="Read routes"
                    v={
                      healthQ.data.features?.routes?.read ? (
                        <Badge variant="success">enabled</Badge>
                      ) : (
                        <Badge variant="secondary">disabled</Badge>
                      )
                    }
                  />
                  <KeyValue
                    k="Ingest routes"
                    v={
                      healthQ.data.features?.routes?.ingest ? (
                        <Badge variant="success">enabled</Badge>
                      ) : (
                        <Badge variant="secondary">disabled</Badge>
                      )
                    }
                  />
                  <KeyValue
                    k="Admin routes"
                    v={
                      healthQ.data.features?.admin?.enabled ? (
                        <div className="flex items-center gap-2">
                          <Badge variant="success">enabled</Badge>
                          <span className="font-mono text-xs">mode: {healthQ.data.features?.admin?.auth_mode ?? 'key'}</span>
                        </div>
                      ) : (
                        <Badge variant="secondary">disabled</Badge>
                      )
                    }
                  />
                  <KeyValue
                    k="Ingest mode"
                    v={
                      <span className="font-mono text-xs">{healthQ.data.features?.ingest?.pipeline_mode ?? 'direct'}</span>
                    }
                  />
                  <KeyValue
                    k="Retention"
                    v={
                      healthQ.data.features?.retention?.enabled ? (
                        <Badge variant="success">enabled</Badge>
                      ) : (
                        <Badge variant="secondary">disabled</Badge>
                      )
                    }
                  />
                  <KeyValue
                    k="Analytics export"
                    v={
                      healthQ.data.features?.analytics_export?.enabled ? (
                        <Badge variant="success">enabled</Badge>
                      ) : (
                        <Badge variant="secondary">disabled</Badge>
                      )
                    }
                  />
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Contracts</CardTitle>
            <CardDescription>
              Active telemetry and edge-policy contracts used for ingest validation, policy enforcement, and UI behavior.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div>
              <div className="text-sm font-medium">Telemetry</div>
              {telemetryContractQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {telemetryContractQ.isError ? (
                <div className="text-sm text-destructive">Error: {(telemetryContractQ.error as Error).message}</div>
              ) : null}
              {telemetryContractQ.data ? (
                <div className="mt-2">
                  <KeyValue k="Version" v={<span className="font-mono text-xs">{telemetryContractQ.data.version}</span>} />
                  <KeyValue
                    k="sha256"
                    v={<span className="font-mono text-xs">{telemetryContractQ.data.sha256.slice(0, 16)}…</span>}
                  />
                  <KeyValue
                    k="Metric keys"
                    v={<span className="font-mono text-xs">{Object.keys(telemetryContractQ.data.metrics).length}</span>}
                  />
                </div>
              ) : null}

              <Separator className="my-4" />

              <div className="text-sm font-medium">Edge policy</div>
              {edgePolicyQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {edgePolicyQ.isError ? (
                <div className="text-sm text-destructive">Error: {(edgePolicyQ.error as Error).message}</div>
              ) : null}
              {edgePolicyQ.data ? (
                <div className="mt-2">
                  <KeyValue k="Version" v={<span className="font-mono text-xs">{edgePolicyQ.data.policy_version}</span>} />
                  <KeyValue k="sha256" v={<span className="font-mono text-xs">{edgePolicyQ.data.policy_sha256.slice(0, 16)}…</span>} />
                  <KeyValue k="Sample interval" v={<span className="font-mono text-xs">{edgePolicyQ.data.reporting.sample_interval_s}s</span>} />
                  <KeyValue k="Heartbeat interval" v={<span className="font-mono text-xs">{edgePolicyQ.data.reporting.heartbeat_interval_s}s</span>} />
                </div>
              ) : null}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Links</CardTitle>
          <CardDescription>Useful endpoints and documentation.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3 text-sm">
          <a href="/api/v1/health" target="_blank" rel="noreferrer" className="underline">
            /api/v1/health
          </a>
          <a href="/readyz" target="_blank" rel="noreferrer" className="underline">
            /readyz
          </a>
          <a href="/api/v1/event-stream" target="_blank" rel="noreferrer" className="underline">
            /api/v1/event-stream
          </a>

          {healthQ.data?.features?.docs?.enabled ? (
            <>
              <a href="/docs" target="_blank" rel="noreferrer" className="underline">
                Swagger
              </a>
              <a href="/redoc" target="_blank" rel="noreferrer" className="underline">
                ReDoc
              </a>
              <a href="/openapi.json" target="_blank" rel="noreferrer" className="underline">
                OpenAPI
              </a>
            </>
          ) : (
            <span className="text-muted-foreground">API docs are disabled in this environment.</span>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Operator Search</CardTitle>
          <CardDescription>Unified backend search across devices, fleets, alerts, events, invocations, and deployments.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search devices, fleets, alerts, events…" />
            <Button variant="outline" onClick={() => setSearch('')}>Clear</Button>
          </div>
          <Input
            value={entityTypesInput}
            onChange={(e) => setEntityTypesInput(e.target.value)}
            placeholder="device,fleet,alert,device_event,procedure_invocation,deployment"
          />
          {!search.trim() ? <div className="text-sm text-muted-foreground">Enter a query to search operator-visible entities.</div> : null}
          {searchQ.isLoading ? <div className="text-sm text-muted-foreground">Searching…</div> : null}
          {searchQ.isError ? <div className="text-sm text-destructive">Error: {(searchQ.error as Error).message}</div> : null}
          {(searchQ.data?.items.length ?? 0) > 0 ? (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                <span>
                  Showing {Math.min(searchQ.data?.total ?? 0, searchOffset + 1)}-{Math.min(searchQ.data?.total ?? 0, searchOffset + (searchQ.data?.items.length ?? 0))} of {searchQ.data?.total ?? 0}
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    onClick={() => setSearchOffset((current) => Math.max(0, current - searchLimit))}
                    disabled={searchOffset <= 0}
                  >
                    Previous page
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => setSearchOffset((current) => current + searchLimit)}
                    disabled={(searchQ.data?.offset ?? 0) + (searchQ.data?.limit ?? searchLimit) >= (searchQ.data?.total ?? 0)}
                  >
                    Next page
                  </Button>
                </div>
              </div>
              {searchQ.data?.items.map((row) => (
                <div key={`${row.entity_type}:${row.entity_id}`} className="rounded-md border bg-background p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{row.entity_type}</Badge>
                    <div className="text-sm font-medium">{row.title}</div>
                    {row.device_id ? <div className="font-mono text-xs text-muted-foreground">{row.device_id}</div> : null}
                    <div className="ml-auto">{searchLink(row)}</div>
                    {row.created_at ? <div className="ml-auto text-xs text-muted-foreground">{new Date(row.created_at).toLocaleString()}</div> : null}
                  </div>
                  {row.subtitle ? <div className="mt-1 text-sm text-muted-foreground">{row.subtitle}</div> : null}
                </div>
              ))}
            </div>
          ) : null}
          {search.trim() && !searchQ.isLoading && !searchQ.isError && (searchQ.data?.items.length ?? 0) === 0 ? (
            <div className="text-sm text-muted-foreground">No results.</div>
          ) : null}
        </CardContent>
      </Card>
    </Page>
  )
}
