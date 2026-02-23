import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link } from '@tanstack/react-router'
import { useDebouncedValue } from '@tanstack/react-pacer/debouncer'
import {
  api,
  type AdminEventOut,
  type DriftEventOut,
  type ExportBatchOut,
  type IngestionBatchOut,
  type NotificationEventOut,
} from '../api'
import { useAppSettings } from '../app/settings'
import { useAdminAccess } from '../hooks/useAdminAccess'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Checkbox,
  DataTable,
  Input,
  Label,
  Page,
  useToast,
} from '../ui-kit'
import { fmtDateTime } from '../utils/format'
import { adminAccessHint } from '../utils/adminAuth'

type AdminTab = 'events' | 'ingestions' | 'drift' | 'notifications' | 'exports'

function Callout(props: { title: string; children: React.ReactNode; tone?: 'default' | 'warning' }) {
  const warning = props.tone === 'warning'
  return (
    <div className={warning ? 'rounded-lg border border-destructive/60 bg-destructive/10 p-4 shadow-sm' : 'rounded-lg border bg-muted/30 p-4'}>
      <div className={warning ? 'text-sm font-semibold text-destructive' : 'text-sm font-medium'}>{props.title}</div>
      <div className={warning ? 'mt-1 text-sm text-foreground' : 'mt-1 text-sm text-muted-foreground'}>{props.children}</div>
    </div>
  )
}

export function AdminPage() {
  const { adminKey } = useAppSettings()
  const healthQ = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })

  const adminEnabled = Boolean(healthQ.data?.features?.admin?.enabled)
  const adminAuthMode = String(healthQ.data?.features?.admin?.auth_mode ?? 'key').toLowerCase()
  const { adminAccess, adminCred, keyRequired, keyInvalid, keyValidating } = useAdminAccess({
    adminEnabled,
    adminAuthMode,
    adminKey,
  })
  const inputsDisabled = !adminAccess

  const { toast } = useToast()
  const [tab, setTab] = React.useState<AdminTab>('ingestions')

  const qc = useQueryClient()

  React.useEffect(() => {
    // Ensure admin datasets refetch whenever auth posture changes (mode or key),
    // so stale 401 errors from a previous key do not stick around.
    qc.invalidateQueries({ queryKey: ['admin'] })
  }, [qc, adminAuthMode, adminKey])

  // Device provisioning (admin-only).
  const [provId, setProvId] = React.useState('')
  const [provName, setProvName] = React.useState('')
  const [provToken, setProvToken] = React.useState('')
  const [provHeartbeat, setProvHeartbeat] = React.useState('300')
  const [provOfflineAfter, setProvOfflineAfter] = React.useState('900')
  const [provEnabled, setProvEnabled] = React.useState(true)
  const [provStatus, setProvStatus] = React.useState<string | null>(null)

  const upsertMutation = useMutation({
    mutationFn: async () => {
      const id = provId.trim()
      const token = provToken.trim()
      if (adminAuthMode === 'key' && !adminAccess) throw new Error('Valid admin key required')
      if (!id) throw new Error('Device ID is required')
      if (!token) throw new Error('Token is required')

      const heartbeat = Number(provHeartbeat)
      const offlineAfter = Number(provOfflineAfter)
      if (!Number.isFinite(heartbeat) || heartbeat <= 0) throw new Error('Heartbeat must be a positive number')
      if (!Number.isFinite(offlineAfter) || offlineAfter <= 0) throw new Error('Offline after must be a positive number')

      try {
        return await api.admin.createDevice(adminCred, {
          device_id: id,
          display_name: provName.trim() || undefined,
          token,
          heartbeat_interval_s: heartbeat,
          offline_after_s: offlineAfter,
        })
      } catch (e) {
        const msg = (e as Error).message
        if (msg.startsWith('409')) {
          // Upsert behavior: if the device already exists, patch it.
          return await api.admin.updateDevice(adminCred, id, {
            display_name: provName.trim() || undefined,
            token,
            heartbeat_interval_s: heartbeat,
            offline_after_s: offlineAfter,
            enabled: provEnabled,
          })
        }
        throw e
      }
    },
    onMutate: () => {
      setProvStatus(null)
    },
    onSuccess: (d) => {
      setProvStatus(`Device provisioned: ${d.device_id}`)
      toast({
        title: 'Device provisioned',
        description: d.device_id,
        variant: 'success',
      })
      // Keep fleet views fresh.
      qc.invalidateQueries({ queryKey: ['devices'] })
      qc.invalidateQueries({ queryKey: ['devicesSummary'] })
    },
    onError: (e) => {
      setProvStatus(`Error: ${(e as Error).message}`)
      toast({
        title: 'Provision failed',
        description: (e as Error).message,
        variant: 'error',
      })
    },
  })

  const [deviceRaw, setDeviceRaw] = React.useState('')
  const [deviceId] = useDebouncedValue(deviceRaw.trim(), { wait: 250 })

  const [statusRaw, setStatusRaw] = React.useState('')
  const [statusFilter] = useDebouncedValue(statusRaw.trim(), { wait: 250 })

  const ingestionsQ = useQuery({
    queryKey: ['admin', 'ingestions', deviceId],
    queryFn: () => api.admin.ingestions(adminCred, { device_id: deviceId || undefined, limit: 300 }),
    enabled: tab === 'ingestions' && adminAccess,
  })

  const driftQ = useQuery({
    queryKey: ['admin', 'drift', deviceId],
    queryFn: () => api.admin.driftEvents(adminCred, { device_id: deviceId || undefined, limit: 300 }),
    enabled: tab === 'drift' && adminAccess,
  })

  const notificationsQ = useQuery({
    queryKey: ['admin', 'notifications', deviceId],
    queryFn: () => api.admin.notifications(adminCred, { device_id: deviceId || undefined, limit: 300 }),
    enabled: tab === 'notifications' && adminAccess,
  })

  const eventsQ = useQuery({
    queryKey: ['admin', 'events'],
    queryFn: () => api.admin.events(adminCred, { limit: 300 }),
    enabled: tab === 'events' && adminAccess,
  })

  const exportsQ = useQuery({
    queryKey: ['admin', 'exports', statusFilter],
    queryFn: () => api.admin.exports(adminCred, { status: statusFilter || undefined, limit: 300 }),
    enabled: tab === 'exports' && adminAccess,
  })

  const ingestionCols = React.useMemo<ColumnDef<IngestionBatchOut>[]>(() => {
    return [
      { header: 'Device', accessorKey: 'device_id', cell: (i) => <Link to="/devices/$deviceId" params={{ deviceId: String(i.getValue()) }} className="font-mono text-xs">{String(i.getValue())}</Link> },
      { header: 'Received', accessorKey: 'received_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as any)}</span> },
      { header: 'Accepted', accessorKey: 'points_accepted', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Dupes', accessorKey: 'duplicates', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Quarantine', accessorKey: 'points_quarantined', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Unknown keys', cell: (i) => <span className="font-mono text-xs">{(i.row.original.unknown_metric_keys ?? []).length}</span> },
      { header: 'Type mismatches', cell: (i) => <span className="font-mono text-xs">{(i.row.original.type_mismatch_keys ?? []).length}</span> },
      { header: 'Contract', cell: (i) => <span className="font-mono text-xs">{i.row.original.contract_version}</span> },
      { header: 'Status', accessorKey: 'processing_status', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
    ]
  }, [])

  const driftCols = React.useMemo<ColumnDef<DriftEventOut>[]>(() => {
    return [
      { header: 'Device', accessorKey: 'device_id', cell: (i) => <Link to="/devices/$deviceId" params={{ deviceId: String(i.getValue()) }} className="font-mono text-xs">{String(i.getValue())}</Link> },
      { header: 'Created', accessorKey: 'created_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as any)}</span> },
      { header: 'Type', accessorKey: 'event_type' },
      { header: 'Action', accessorKey: 'action', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
      { header: 'Batch', accessorKey: 'batch_id', cell: (i) => <span className="font-mono text-xs">{String(i.getValue()).slice(0, 10)}…</span> },
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
      { header: 'Device', accessorKey: 'device_id', cell: (i) => <Link to="/devices/$deviceId" params={{ deviceId: String(i.getValue()) }} className="font-mono text-xs">{String(i.getValue())}</Link> },
      { header: 'Created', accessorKey: 'created_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as any)}</span> },
      { header: 'Type', accessorKey: 'alert_type' },
      { header: 'Channel', accessorKey: 'channel', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
      { header: 'Decision', accessorKey: 'decision' },
      { header: 'Delivered', accessorKey: 'delivered', cell: (i) => (i.getValue() ? <Badge variant="success">yes</Badge> : <Badge variant="destructive">no</Badge>) },
      { header: 'Reason', accessorKey: 'reason', cell: (i) => <span className="text-muted-foreground">{String(i.getValue())}</span> },
    ]
  }, [])

  const eventCols = React.useMemo<ColumnDef<AdminEventOut>[]>(() => {
    return [
      { header: 'Created', accessorKey: 'created_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as any)}</span> },
      { header: 'Action', accessorKey: 'action', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
      { header: 'Actor', accessorKey: 'actor_email', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Subject', accessorKey: 'actor_subject', cell: (i) => (i.getValue() ? <span className="font-mono text-xs">{String(i.getValue())}</span> : <span className="text-muted-foreground">—</span>) },
      { header: 'Target', accessorKey: 'target_device_id', cell: (i) => (i.getValue() ? <Link to="/devices/$deviceId" params={{ deviceId: String(i.getValue()) }} className="font-mono text-xs">{String(i.getValue())}</Link> : <span className="text-muted-foreground">—</span>) },
      { header: 'Request ID', accessorKey: 'request_id', cell: (i) => (i.getValue() ? <span className="font-mono text-xs">{String(i.getValue())}</span> : <span className="text-muted-foreground">—</span>) },
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

  const exportCols = React.useMemo<ColumnDef<ExportBatchOut>[]>(() => {
    return [
      { header: 'Started', accessorKey: 'started_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as any)}</span> },
      { header: 'Finished', accessorKey: 'finished_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as any)}</span> },
      { header: 'Rows', accessorKey: 'row_count', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Status', accessorKey: 'status', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
      { header: 'GCS URI', accessorKey: 'gcs_uri', cell: (i) => (i.getValue() ? <span className="font-mono text-xs">{String(i.getValue())}</span> : <span className="text-muted-foreground">—</span>) },
      { header: 'Contract', accessorKey: 'contract_version', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Error', accessorKey: 'error_message', cell: (i) => (i.getValue() ? <span className="text-destructive">{String(i.getValue())}</span> : <span className="text-muted-foreground">—</span>) },
    ]
  }, [])

  const tabs: Array<{ key: AdminTab; label: string }> = [
    { key: 'events', label: 'Events' },
    { key: 'ingestions', label: 'Ingestions' },
    { key: 'drift', label: 'Drift' },
    { key: 'notifications', label: 'Notifications' },
    { key: 'exports', label: 'Exports' },
  ]

  const active = tab === 'events' ? eventsQ : tab === 'ingestions' ? ingestionsQ : tab === 'drift' ? driftQ : tab === 'notifications' ? notificationsQ : exportsQ
  const activeAccessHint = React.useMemo(() => adminAccessHint(active.error, adminAuthMode), [active.error, adminAuthMode])

  return (
    <Page
      title="Admin"
      description="Audit trails for admin mutations, ingestion, contract drift, notifications, and exports."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {tabs.map((t) => (
            <Button key={t.key} size="sm" variant={tab === t.key ? 'default' : 'outline'} onClick={() => setTab(t.key)}>
              {t.label}
            </Button>
          ))}
          {!healthQ.isSuccess ? (
            <Badge variant="outline" className="ml-auto">
              checking…
            </Badge>
          ) : !adminEnabled ? (
            <Badge variant="outline" className="ml-auto">
              admin routes disabled
            </Badge>
          ) : adminAuthMode === 'none' ? (
            <Badge variant="success" className="ml-auto">
              admin: IAM
            </Badge>
          ) : keyValidating ? (
            <Badge variant="outline" className="ml-auto">
              validating key…
            </Badge>
          ) : adminAccess ? (
            <Badge variant="success" className="ml-auto">
              admin: key
            </Badge>
          ) : keyInvalid ? (
            <Badge variant="destructive" className="ml-auto">
              invalid key
            </Badge>
          ) : (
            <Badge variant="outline" className="ml-auto">
              admin key needed
            </Badge>
          )}
        </div>
      }
    >
      {!healthQ.isSuccess ? (
        <Callout title="Loading">
          Checking server capabilities…
        </Callout>
      ) : !adminEnabled ? (
        <Callout title="Admin API not enabled">
          This deployment was configured with <span className="font-mono">ENABLE_ADMIN_ROUTES=0</span>.
          Use the dedicated admin service (recommended) or enable admin routes for this service.
          See <Link to="/meta" className="underline">System</Link> for environment details.
        </Callout>
      ) : keyRequired ? (
        <Callout title="Admin key required" tone="warning">
          Configure an admin key in <Link to="/settings" className="underline">Settings</Link>.
        </Callout>
      ) : keyValidating ? (
        <Callout title="Validating admin key">Checking admin access…</Callout>
      ) : keyInvalid ? (
        <Callout title="Invalid admin key" tone="warning">
          The configured key was rejected. Update it in <Link to="/settings" className="underline">Settings</Link>.
        </Callout>
      ) : null}

      {adminAccess ? (
        <Card>
          <CardHeader>
            <CardTitle>Provision a device</CardTitle>
            <CardDescription>
              Create (or update) a device registration and generate a token you can paste into the edge agent.
              If the device already exists, this form will update it.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 lg:grid-cols-3">
            <div className="space-y-2">
              <Label>Device ID</Label>
              <Input value={provId} onChange={(e) => setProvId(e.target.value)} placeholder="well-001" disabled={inputsDisabled} />
            </div>
            <div className="space-y-2">
              <Label>Display name (optional)</Label>
              <Input value={provName} onChange={(e) => setProvName(e.target.value)} placeholder="Well 001" disabled={inputsDisabled} />
            </div>
            <div className="space-y-2">
              <Label>Token</Label>
              <div className="flex gap-2">
                <Input
                  value={provToken}
                  onChange={(e) => setProvToken(e.target.value)}
                  placeholder="paste or generate"
                  disabled={inputsDisabled}
                />
                <Button
                  type="button"
                  variant="outline"
                  disabled={inputsDisabled}
                  onClick={() => {
                    const t = (globalThis.crypto?.randomUUID?.() ?? String(Math.random())).replace(/-/g, '')
                    setProvToken(t)
                  }}
                >
                  Generate
                </Button>
              </div>
              <div className="text-xs text-muted-foreground">Treat tokens like passwords (store them in a secret manager).</div>
            </div>

            <div className="space-y-2">
              <Label>Heartbeat interval (seconds)</Label>
              <Input
                value={provHeartbeat}
                onChange={(e) => setProvHeartbeat(e.target.value)}
                placeholder="300"
                disabled={inputsDisabled}
              />
            </div>
            <div className="space-y-2">
              <Label>Offline after (seconds)</Label>
              <Input
                value={provOfflineAfter}
                onChange={(e) => setProvOfflineAfter(e.target.value)}
                placeholder="900"
                disabled={inputsDisabled}
              />
            </div>
            <div className="space-y-2">
              <Label>Enabled</Label>
              <div className="flex items-center gap-2">
                <Checkbox checked={provEnabled} onChange={(e) => setProvEnabled(e.target.checked)} disabled={inputsDisabled} />
                <span className="text-sm text-muted-foreground">Device can ingest telemetry</span>
              </div>
            </div>

            <div className="lg:col-span-3 flex flex-wrap items-center gap-2">
              <Button
                type="button"
                disabled={inputsDisabled || upsertMutation.isPending}
                onClick={() => upsertMutation.mutate()}
              >
                {upsertMutation.isPending ? 'Saving…' : 'Create / Update device'}
              </Button>
              {provStatus ? <span className={provStatus.startsWith('Error') ? 'text-sm text-destructive' : 'text-sm text-muted-foreground'}>{provStatus}</span> : null}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {healthQ.isSuccess && adminEnabled ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Filters</CardTitle>
              <CardDescription>Filters apply to the active tab.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 lg:grid-cols-3">
              <div className="space-y-2">
                <Label>Device ID (optional)</Label>
                <Input
                  value={deviceRaw}
                  onChange={(e) => setDeviceRaw(e.target.value)}
                  placeholder="device-001"
                  disabled={inputsDisabled}
                />
              </div>
              <div className="space-y-2">
                <Label>Status (exports tab)</Label>
                <Input
                  value={statusRaw}
                  onChange={(e) => setStatusRaw(e.target.value)}
                  placeholder="success | failed | running"
                  disabled={inputsDisabled}
                />
              </div>
              <div className="space-y-2">
                <Label>Notes</Label>
                <div className="text-xs text-muted-foreground">
                  Ingestions/drift/notifications support a device filter. Exports support a status filter.
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Results</CardTitle>
              <CardDescription>
                {tab === 'ingestions'
                  ? 'Each row is an ingest batch with contract validation stats.'
                  : tab === 'events'
                    ? 'Admin mutation audit events with acting principal attribution.'
                  : tab === 'drift'
                    ? 'Drift events generated by contract enforcement.'
                    : tab === 'notifications'
                      ? 'Notification audit trail (delivered/blocked + why).'
                      : 'BigQuery export batches.'}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {active.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {active.isError ? (
                <div className="text-sm text-destructive">Error: {(active.error as Error).message}</div>
              ) : null}
              {active.isError && activeAccessHint ? (
                <Callout title="Access guidance">{activeAccessHint}</Callout>
              ) : null}
              {tab === 'ingestions' ? (
                <DataTable<IngestionBatchOut>
                  data={ingestionsQ.data ?? []}
                  columns={ingestionCols}
                  height={560}
                  enableSorting
                  initialSorting={[{ id: 'received_at', desc: true }]}
                  emptyState="No batches found."
                />
              ) : null}
              {tab === 'events' ? (
                <DataTable<AdminEventOut>
                  data={eventsQ.data ?? []}
                  columns={eventCols}
                  height={560}
                  enableSorting
                  initialSorting={[{ id: 'created_at', desc: true }]}
                  emptyState="No admin events found."
                />
              ) : null}
              {tab === 'drift' ? (
                <DataTable<DriftEventOut>
                  data={driftQ.data ?? []}
                  columns={driftCols}
                  height={560}
                  enableSorting
                  initialSorting={[{ id: 'created_at', desc: true }]}
                  emptyState="No drift events found."
                />
              ) : null}
              {tab === 'notifications' ? (
                <DataTable<NotificationEventOut>
                  data={notificationsQ.data ?? []}
                  columns={notificationCols}
                  height={560}
                  enableSorting
                  initialSorting={[{ id: 'created_at', desc: true }]}
                  emptyState="No notification events found."
                />
              ) : null}
              {tab === 'exports' ? (
                <DataTable<ExportBatchOut>
                  data={exportsQ.data ?? []}
                  columns={exportCols}
                  height={560}
                  enableSorting
                  initialSorting={[{ id: 'started_at', desc: true }]}
                  emptyState="No export batches found."
                />
              ) : null}
            </CardContent>
          </Card>
        </>
      ) : null}

    </Page>
  )
}
