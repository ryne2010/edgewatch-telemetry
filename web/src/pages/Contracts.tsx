import React from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { api } from '../api'
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  DataTable,
  Page,
  Separator,
} from '../ui-kit'

type MetricRow = { key: string; type: string; unit: string; description: string }
type DeltaRow = { key: string; threshold: number }

function KeyValue(props: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b py-2 last:border-b-0">
      <div className="text-sm text-muted-foreground">{props.k}</div>
      <div className="text-sm font-medium">{props.v}</div>
    </div>
  )
}

export function ContractsPage() {
  const telemetryQ = useQuery({ queryKey: ['telemetryContract'], queryFn: api.telemetryContract, staleTime: 5 * 60_000 })
  const policyQ = useQuery({ queryKey: ['edgePolicyContract'], queryFn: api.edgePolicyContract, staleTime: 5 * 60_000 })

  const c = telemetryQ.data
  const p = policyQ.data

  const rows = React.useMemo<MetricRow[]>(() => {
    if (!c) return []
    return Object.entries(c.metrics)
      .map(([key, m]) => ({
        key,
        type: m.type,
        unit: m.unit ?? '—',
        description: m.description ?? '—',
      }))
      .sort((a, b) => a.key.localeCompare(b.key))
  }, [c])

  const cols = React.useMemo<ColumnDef<MetricRow>[]>(() => {
    return [
      { header: 'Key', accessorKey: 'key', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Type', accessorKey: 'type', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
      { header: 'Unit', accessorKey: 'unit' },
      {
        header: 'Description',
        accessorKey: 'description',
        cell: (i) => <span className="text-muted-foreground">{String(i.getValue())}</span>,
      },
    ]
  }, [])

  const deltaRows = React.useMemo<DeltaRow[]>(() => {
    if (!p) return []
    return Object.entries(p.delta_thresholds)
      .map(([key, threshold]) => ({ key, threshold }))
      .sort((a, b) => a.key.localeCompare(b.key))
  }, [p])

  const deltaCols = React.useMemo<ColumnDef<DeltaRow>[]>(() => {
    return [
      { header: 'Metric', accessorKey: 'key', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      {
        header: 'Δ threshold',
        accessorKey: 'threshold',
        cell: (i) => <span className="font-mono text-xs">{Number(i.getValue()).toString()}</span>,
      },
    ]
  }, [])

  return (
    <Page
      title="Contracts"
      description="Contracts are the source of truth for ingest validation, UI options, and edge reporting optimizations."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {c ? <Badge variant="outline">telemetry: v{c.version}</Badge> : null}
          {p ? <Badge variant="outline">policy: {p.policy_version}</Badge> : null}
        </div>
      }
    >
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Telemetry contract</CardTitle>
            <CardDescription>
              Allowed metric keys + types + units. The ingest pipeline enforces this contract and audits drift.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {telemetryQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
            {telemetryQ.isError ? <div className="text-sm text-destructive">Error: {(telemetryQ.error as Error).message}</div> : null}

            {c ? (
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <Badge variant="secondary">sha: {c.sha256.slice(0, 12)}…</Badge>
                <Badge variant="outline">metrics: {Object.keys(c.metrics).length}</Badge>
              </div>
            ) : null}

            <DataTable<MetricRow>
              data={rows}
              columns={cols}
              height={520}
              enableSorting
              initialSorting={[{ id: 'key', desc: false }]}
              emptyState="No contract loaded."
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Edge policy contract</CardTitle>
            <CardDescription>
              Defines sampling cadence, batching, delta thresholds (edge de-dup), and alert thresholds.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {policyQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
            {policyQ.isError ? <div className="text-sm text-destructive">Error: {(policyQ.error as Error).message}</div> : null}

            {p ? (
              <>
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">sha: {p.policy_sha256.slice(0, 12)}…</Badge>
                  <Badge variant="outline">cache: {p.cache_max_age_s}s</Badge>
                </div>

                <div className="grid gap-6 lg:grid-cols-2">
                  <div>
                    <div className="text-sm font-medium">Reporting</div>
                    <div className="mt-2">
                      <KeyValue k="Sample interval" v={<span className="font-mono text-xs">{p.reporting.sample_interval_s}s</span>} />
                      <KeyValue k="Heartbeat" v={<span className="font-mono text-xs">{p.reporting.heartbeat_interval_s}s</span>} />
                      <KeyValue k="Alert sample interval" v={<span className="font-mono text-xs">{p.reporting.alert_sample_interval_s}s</span>} />
                      <KeyValue k="Alert report interval" v={<span className="font-mono text-xs">{p.reporting.alert_report_interval_s}s</span>} />
                      <KeyValue k="Max points / batch" v={<span className="font-mono text-xs">{p.reporting.max_points_per_batch}</span>} />
                    </div>
                  </div>

                  <div>
                    <div className="text-sm font-medium">Alert thresholds</div>
                    <div className="mt-2">
                      <KeyValue
                        k="Water pressure low"
                        v={<span className="font-mono text-xs">{p.alert_thresholds.water_pressure_low_psi} psi</span>}
                      />
                      <KeyValue
                        k="Water recover"
                        v={<span className="font-mono text-xs">{p.alert_thresholds.water_pressure_recover_psi} psi</span>}
                      />
                      <KeyValue
                        k="Oil pressure low"
                        v={<span className="font-mono text-xs">{p.alert_thresholds.oil_pressure_low_psi} psi</span>}
                      />
                      <KeyValue
                        k="Oil pressure recover"
                        v={<span className="font-mono text-xs">{p.alert_thresholds.oil_pressure_recover_psi} psi</span>}
                      />
                      <KeyValue
                        k="Oil level low"
                        v={<span className="font-mono text-xs">{p.alert_thresholds.oil_level_low_pct}%</span>}
                      />
                      <KeyValue
                        k="Oil level recover"
                        v={<span className="font-mono text-xs">{p.alert_thresholds.oil_level_recover_pct}%</span>}
                      />
                      <KeyValue
                        k="Drip oil low"
                        v={<span className="font-mono text-xs">{p.alert_thresholds.drip_oil_level_low_pct}%</span>}
                      />
                      <KeyValue
                        k="Drip oil recover"
                        v={<span className="font-mono text-xs">{p.alert_thresholds.drip_oil_level_recover_pct}%</span>}
                      />
                      <KeyValue
                        k="Oil life low"
                        v={<span className="font-mono text-xs">{p.alert_thresholds.oil_life_low_pct}%</span>}
                      />
                      <KeyValue
                        k="Oil life recover"
                        v={<span className="font-mono text-xs">{p.alert_thresholds.oil_life_recover_pct}%</span>}
                      />
                      <KeyValue k="Battery low" v={<span className="font-mono text-xs">{p.alert_thresholds.battery_low_v} V</span>} />
                      <KeyValue
                        k="Battery recover"
                        v={<span className="font-mono text-xs">{p.alert_thresholds.battery_recover_v} V</span>}
                      />
                      <KeyValue
                        k="Signal low"
                        v={<span className="font-mono text-xs">{p.alert_thresholds.signal_low_rssi_dbm} dBm</span>}
                      />
                      <KeyValue
                        k="Signal recover"
                        v={<span className="font-mono text-xs">{p.alert_thresholds.signal_recover_rssi_dbm} dBm</span>}
                      />
                    </div>
                  </div>
                </div>

                <Separator className="my-4" />

                <div className="text-sm font-medium">Delta thresholds</div>
                <div className="mt-2 text-xs text-muted-foreground">
                  Edge devices can suppress sending points if values change less than these deltas.
                </div>

                <div className="mt-3">
                  <DataTable<DeltaRow>
                    data={deltaRows}
                    columns={deltaCols}
                    height={320}
                    enableSorting
                    initialSorting={[{ id: 'key', desc: false }]}
                    emptyState="No delta thresholds."
                  />
                </div>
              </>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}
