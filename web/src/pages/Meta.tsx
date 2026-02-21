import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Page, Separator } from '../ui-kit'

function KeyValue(props: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b py-2 last:border-b-0">
      <div className="text-sm text-muted-foreground">{props.k}</div>
      <div className="text-sm font-medium">{props.v}</div>
    </div>
  )
}

export function MetaPage() {
  const healthQ = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 60_000 })
  const telemetryContractQ = useQuery({ queryKey: ['telemetryContract'], queryFn: api.telemetryContract, staleTime: 5 * 60_000 })
  const edgePolicyQ = useQuery({ queryKey: ['edgePolicyContract'], queryFn: api.edgePolicyContract, staleTime: 5 * 60_000 })

  const env = healthQ.data?.env
  const version = healthQ.data?.version

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
            <CardDescription>Contracts drive edge optimization, UI options, and ingest validation.</CardDescription>
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
    </Page>
  )
}
