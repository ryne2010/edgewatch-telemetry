import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link, useSearch } from '@tanstack/react-router'
import { useDebouncedValue } from '@tanstack/react-pacer/debouncer'
import {
  api,
  type AdminEventOut,
  type DeviceProcedureDefinitionOut,
  type DeviceAccessGrantOut,
  type DriftEventOut,
  type ExportBatchOut,
  type FleetOut,
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
  const routeSearch = useSearch({ from: '/admin' })
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
  const otaUpdatesEnabled = Boolean(healthQ.data?.features?.routes?.ota_updates)
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
  const [provOwners, setProvOwners] = React.useState('')
  const [provEnabled, setProvEnabled] = React.useState(true)
  const [provStatus, setProvStatus] = React.useState<string | null>(null)
  const [accessDeviceId, setAccessDeviceId] = React.useState('')
  const [accessPrincipalEmail, setAccessPrincipalEmail] = React.useState('')
  const [accessRole, setAccessRole] = React.useState<'viewer' | 'operator' | 'owner'>('viewer')
  const [shutdownDeviceId, setShutdownDeviceId] = React.useState('')
  const [shutdownReason, setShutdownReason] = React.useState('seasonal intermission')
  const [shutdownGraceS, setShutdownGraceS] = React.useState('30')
  const [fleetName, setFleetName] = React.useState('')
  const [fleetDescription, setFleetDescription] = React.useState('')
  const [fleetDefaultChannel, setFleetDefaultChannel] = React.useState('stable')
  const [fleetSelectedId, setFleetSelectedId] = React.useState('')
  const [fleetDeviceId, setFleetDeviceId] = React.useState('')
  const [fleetAccessEmail, setFleetAccessEmail] = React.useState('')
  const [fleetAccessRole, setFleetAccessRole] = React.useState<'viewer' | 'operator' | 'owner'>('viewer')
  const [procedureName, setProcedureName] = React.useState('')
  const [procedureDescription, setProcedureDescription] = React.useState('')
  const [procedureTimeoutS, setProcedureTimeoutS] = React.useState('300')
  const [procedureRequestSchema, setProcedureRequestSchema] = React.useState('{}')
  const [procedureResponseSchema, setProcedureResponseSchema] = React.useState('{}')
  const [procedureFilterRaw, setProcedureFilterRaw] = React.useState('')
  const [procedureFilter] = useDebouncedValue(procedureFilterRaw.trim(), { wait: 250 })

  const upsertMutation = useMutation({
    mutationFn: async () => {
      const id = provId.trim()
      const name = provName.trim() || id
      const token = provToken.trim()
      if (adminAuthMode === 'key' && !adminAccess) throw new Error('Valid admin key required')
      if (!id) throw new Error('Device ID is required')
      if (!token) throw new Error('Token is required')

      const heartbeat = Number(provHeartbeat)
      const offlineAfter = Number(provOfflineAfter)
      if (!Number.isFinite(heartbeat) || heartbeat <= 0) throw new Error('Heartbeat must be a positive number')
      if (!Number.isFinite(offlineAfter) || offlineAfter <= 0) throw new Error('Offline after must be a positive number')
      const ownerEmails = Array.from(
        new Set(
          provOwners
            .split(',')
            .map((email) => email.trim().toLowerCase())
            .filter((email) => email.includes('@')),
        ),
      )

      try {
        return await api.admin.createDevice(adminCred, {
          device_id: id,
          display_name: name,
          token,
          heartbeat_interval_s: heartbeat,
          offline_after_s: offlineAfter,
          owner_emails: ownerEmails.length ? ownerEmails : undefined,
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

  const [batchIdRaw, setBatchIdRaw] = React.useState('')
  const [batchIdFilter] = useDebouncedValue(batchIdRaw.trim(), { wait: 250 })
  const [statusRaw, setStatusRaw] = React.useState('')
  const [statusFilter] = useDebouncedValue(statusRaw.trim(), { wait: 250 })
  const [exportIdRaw, setExportIdRaw] = React.useState('')
  const [exportIdFilter] = useDebouncedValue(exportIdRaw.trim(), { wait: 250 })
  const [eventActionRaw, setEventActionRaw] = React.useState('')
  const [eventActionFilter] = useDebouncedValue(eventActionRaw.trim(), { wait: 250 })
  const [eventTargetTypeRaw, setEventTargetTypeRaw] = React.useState('')
  const [eventTargetTypeFilter] = useDebouncedValue(eventTargetTypeRaw.trim(), { wait: 250 })
  const [notificationSourceKindRaw, setNotificationSourceKindRaw] = React.useState('')
  const [notificationSourceKindFilter] = useDebouncedValue(notificationSourceKindRaw.trim(), { wait: 250 })
  const [notificationChannelRaw, setNotificationChannelRaw] = React.useState('')
  const [notificationChannelFilter] = useDebouncedValue(notificationChannelRaw.trim(), { wait: 250 })
  const [notificationDecisionRaw, setNotificationDecisionRaw] = React.useState('')
  const [notificationDecisionFilter] = useDebouncedValue(notificationDecisionRaw.trim(), { wait: 250 })
  const [notificationDeliveredOnly, setNotificationDeliveredOnly] = React.useState(false)
  const [notificationFailedOnly, setNotificationFailedOnly] = React.useState(false)
  const [eventOffset, setEventOffset] = React.useState(0)
  const eventLimit = 100
  const [ingestionOffset, setIngestionOffset] = React.useState(0)
  const ingestionLimit = 100
  const [driftOffset, setDriftOffset] = React.useState(0)
  const driftLimit = 100
  const [notificationOffset, setNotificationOffset] = React.useState(0)
  const notificationLimit = 100
  const [exportOffset, setExportOffset] = React.useState(0)
  const exportLimit = 100

  React.useEffect(() => {
    if (routeSearch.tab === 'events' || routeSearch.tab === 'ingestions' || routeSearch.tab === 'drift' || routeSearch.tab === 'notifications' || routeSearch.tab === 'exports') {
      setTab(routeSearch.tab)
    }
    if (routeSearch.deviceId) setDeviceRaw(routeSearch.deviceId)
    if (routeSearch.batchId) setBatchIdRaw(routeSearch.batchId)
    if (routeSearch.accessDeviceId) setAccessDeviceId(routeSearch.accessDeviceId)
    if (routeSearch.fleetId) setFleetSelectedId(routeSearch.fleetId)
    if (routeSearch.status) setStatusRaw(routeSearch.status)
    if (routeSearch.exportId) setExportIdRaw(routeSearch.exportId)
    if (routeSearch.action) setEventActionRaw(routeSearch.action)
    if (routeSearch.targetType) setEventTargetTypeRaw(routeSearch.targetType)
    if (routeSearch.procedureName) setProcedureFilterRaw(routeSearch.procedureName)
    if (routeSearch.sourceKind) setNotificationSourceKindRaw(routeSearch.sourceKind)
    if (routeSearch.channel) setNotificationChannelRaw(routeSearch.channel)
    if (routeSearch.decision) setNotificationDecisionRaw(routeSearch.decision)
    if (routeSearch.delivered === 'true') {
      setNotificationDeliveredOnly(true)
      setNotificationFailedOnly(false)
    } else if (routeSearch.delivered === 'false') {
      setNotificationFailedOnly(true)
      setNotificationDeliveredOnly(false)
    }
  }, [
    routeSearch.action,
    routeSearch.channel,
    routeSearch.decision,
    routeSearch.delivered,
    routeSearch.accessDeviceId,
    routeSearch.batchId,
    routeSearch.deviceId,
    routeSearch.exportId,
    routeSearch.fleetId,
    routeSearch.procedureName,
    routeSearch.sourceKind,
    routeSearch.status,
    routeSearch.tab,
    routeSearch.targetType,
  ])

  const ingestionsQ = useQuery({
    queryKey: ['admin', 'ingestionsPage', deviceId, ingestionOffset],
    queryFn: () =>
      api.admin.ingestionsPage(adminCred, {
        device_id: deviceId || undefined,
        limit: ingestionLimit,
        offset: ingestionOffset,
      }),
    enabled: tab === 'ingestions' && adminAccess,
  })

  const driftQ = useQuery({
    queryKey: ['admin', 'driftPage', deviceId, driftOffset],
    queryFn: () =>
      api.admin.driftEventsPage(adminCred, {
        device_id: deviceId || undefined,
        limit: driftLimit,
        offset: driftOffset,
      }),
    enabled: tab === 'drift' && adminAccess,
  })

  const notificationsQ = useQuery({
    queryKey: [
      'admin',
      'notificationsPage',
      deviceId,
      notificationSourceKindFilter,
      notificationChannelFilter,
      notificationDecisionFilter,
      notificationDeliveredOnly,
      notificationFailedOnly,
      notificationOffset,
    ],
    queryFn: () =>
      api.admin.notificationsPage(adminCred, {
        device_id: deviceId || undefined,
        source_kind: notificationSourceKindFilter || undefined,
        channel: notificationChannelFilter || undefined,
        decision: notificationDecisionFilter || undefined,
        delivered: notificationFailedOnly ? false : notificationDeliveredOnly ? true : undefined,
        limit: notificationLimit,
        offset: notificationOffset,
      }),
    enabled: tab === 'notifications' && adminAccess,
  })

  const eventsQ = useQuery({
    queryKey: ['admin', 'eventsPage', deviceId, eventActionFilter, eventTargetTypeFilter, eventOffset],
    queryFn: () =>
      api.admin.eventsPage(adminCred, {
        limit: eventLimit,
        offset: eventOffset,
        device_id: deviceId || undefined,
        action: eventActionFilter || undefined,
        target_type: eventTargetTypeFilter || undefined,
      }),
    enabled: tab === 'events' && adminAccess,
  })

  React.useEffect(() => {
    setEventOffset(0)
  }, [deviceId, eventActionFilter, eventTargetTypeFilter])

  React.useEffect(() => {
    setIngestionOffset(0)
    setDriftOffset(0)
  }, [deviceId, batchIdFilter])

  React.useEffect(() => {
    setNotificationOffset(0)
  }, [
    deviceId,
    notificationSourceKindFilter,
    notificationChannelFilter,
    notificationDecisionFilter,
    notificationDeliveredOnly,
    notificationFailedOnly,
  ])

  const exportsQ = useQuery({
    queryKey: ['admin', 'exportsPage', statusFilter, exportOffset],
    queryFn: () =>
      api.admin.exportsPage(adminCred, {
        status: statusFilter || undefined,
        limit: exportLimit,
        offset: exportOffset,
      }),
    enabled: tab === 'exports' && adminAccess,
  })

  React.useEffect(() => {
    setExportOffset(0)
  }, [statusFilter, exportIdFilter])

  const filteredExports = React.useMemo(() => {
    const rows = exportsQ.data?.items ?? []
    const q = exportIdFilter.toLowerCase()
    if (!q) return rows
    return rows.filter((row) => row.id.toLowerCase().includes(q))
  }, [exportsQ.data?.items, exportIdFilter])

  const filteredIngestions = React.useMemo(() => {
    const rows = ingestionsQ.data?.items ?? []
    const q = batchIdFilter.toLowerCase()
    if (!q) return rows
    return rows.filter((row) => row.id.toLowerCase().includes(q))
  }, [batchIdFilter, ingestionsQ.data?.items])

  const filteredDrift = React.useMemo(() => {
    const rows = driftQ.data?.items ?? []
    const q = batchIdFilter.toLowerCase()
    if (!q) return rows
    return rows.filter((row) => row.batch_id.toLowerCase().includes(q))
  }, [batchIdFilter, driftQ.data?.items])

  const fleetsQ = useQuery({
    queryKey: ['admin', 'fleets'],
    queryFn: () => api.admin.fleets(adminCred),
    enabled: adminAccess,
  })

  const fleetAccessQ = useQuery({
    queryKey: ['admin', 'fleetAccess', fleetSelectedId.trim()],
    queryFn: () => api.admin.fleetAccess.list(adminCred, fleetSelectedId.trim()),
    enabled: adminAccess && Boolean(fleetSelectedId.trim()),
  })

  const procedureDefinitionsQ = useQuery({
    queryKey: ['admin', 'procedureDefinitions'],
    queryFn: () => api.admin.procedureDefinitions(adminCred),
    enabled: adminAccess,
  })

  const accessDevice = accessDeviceId.trim()
  const deviceAccessQ = useQuery({
    queryKey: ['admin', 'deviceAccess', accessDevice],
    queryFn: () => api.admin.deviceAccess.list(adminCred, accessDevice),
    enabled: adminAccess && Boolean(accessDevice),
  })

  const upsertAccessMutation = useMutation({
    mutationFn: async () => {
      const deviceIdValue = accessDeviceId.trim()
      const email = accessPrincipalEmail.trim().toLowerCase()
      if (!deviceIdValue) throw new Error('Device ID is required for access management.')
      if (!email || !email.includes('@')) throw new Error('Principal email is required.')
      return api.admin.deviceAccess.put(adminCred, deviceIdValue, email, { access_role: accessRole })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'deviceAccess', accessDeviceId.trim()] })
      toast({
        title: 'Device access saved',
        variant: 'success',
      })
      setAccessPrincipalEmail('')
    },
    onError: (error) => {
      toast({
        title: 'Unable to save device access',
        description: (error as Error).message,
        variant: 'error',
      })
    },
  })

  const deleteAccessMutation = useMutation({
    mutationFn: async (email: string) => {
      const deviceIdValue = accessDeviceId.trim()
      if (!deviceIdValue) throw new Error('Device ID is required for access management.')
      return api.admin.deviceAccess.delete(adminCred, deviceIdValue, email)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'deviceAccess', accessDeviceId.trim()] })
      toast({
        title: 'Device access removed',
        variant: 'success',
      })
    },
    onError: (error) => {
      toast({
        title: 'Unable to remove device access',
        description: (error as Error).message,
        variant: 'error',
      })
    },
  })

  const createFleetMutation = useMutation({
    mutationFn: async () => {
      const name = fleetName.trim()
      const default_ota_channel = fleetDefaultChannel.trim()
      if (!name) throw new Error('Fleet name is required.')
      if (!default_ota_channel) throw new Error('Default OTA channel is required.')
      return api.admin.createFleet(adminCred, {
        name,
        description: fleetDescription.trim() || null,
        default_ota_channel,
      })
    },
    onSuccess: (fleet) => {
      qc.invalidateQueries({ queryKey: ['admin', 'fleets'] })
      setFleetSelectedId(fleet.id)
      setFleetName('')
      setFleetDescription('')
      toast({ title: 'Fleet created', description: fleet.name, variant: 'success' })
    },
    onError: (error) => {
      toast({ title: 'Unable to create fleet', description: (error as Error).message, variant: 'error' })
    },
  })

  const addFleetDeviceMutation = useMutation({
    mutationFn: async () => {
      const fleetId = fleetSelectedId.trim()
      const deviceIdValue = fleetDeviceId.trim()
      if (!fleetId) throw new Error('Fleet ID is required.')
      if (!deviceIdValue) throw new Error('Device ID is required.')
      return api.admin.addFleetDevice(adminCred, fleetId, deviceIdValue)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'fleets'] })
      setFleetDeviceId('')
      toast({ title: 'Device added to fleet', variant: 'success' })
    },
    onError: (error) => {
      toast({ title: 'Unable to add device to fleet', description: (error as Error).message, variant: 'error' })
    },
  })

  const putFleetAccessMutation = useMutation({
    mutationFn: async () => {
      const fleetId = fleetSelectedId.trim()
      const email = fleetAccessEmail.trim().toLowerCase()
      if (!fleetId) throw new Error('Fleet ID is required.')
      if (!email || !email.includes('@')) throw new Error('Principal email is required.')
      return api.admin.fleetAccess.put(adminCred, fleetId, email, { access_role: fleetAccessRole })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'fleetAccess', fleetSelectedId.trim()] })
      setFleetAccessEmail('')
      toast({ title: 'Fleet access saved', variant: 'success' })
    },
    onError: (error) => {
      toast({ title: 'Unable to save fleet access', description: (error as Error).message, variant: 'error' })
    },
  })

  const createProcedureDefinitionMutation = useMutation({
    mutationFn: async () => {
      const name = procedureName.trim()
      const timeout_s = Number.parseInt(procedureTimeoutS, 10)
      if (!name) throw new Error('Procedure name is required.')
      if (!Number.isFinite(timeout_s) || timeout_s <= 0) throw new Error('Timeout must be a positive number.')
      let request_schema: Record<string, unknown> = {}
      let response_schema: Record<string, unknown> = {}
      try {
        request_schema = JSON.parse(procedureRequestSchema.trim() || '{}')
        response_schema = JSON.parse(procedureResponseSchema.trim() || '{}')
      } catch {
        throw new Error('Procedure schemas must be valid JSON.')
      }
      return api.admin.createProcedureDefinition(adminCred, {
        name,
        description: procedureDescription.trim() || null,
        request_schema,
        response_schema,
        timeout_s,
        enabled: true,
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'procedureDefinitions'] })
      setProcedureName('')
      setProcedureDescription('')
      setProcedureRequestSchema('{}')
      setProcedureResponseSchema('{}')
      toast({ title: 'Procedure definition created', variant: 'success' })
    },
    onError: (error) => {
      toast({ title: 'Unable to create procedure definition', description: (error as Error).message, variant: 'error' })
    },
  })

  const shutdownMutation = useMutation({
    mutationFn: async () => {
      const deviceIdValue = shutdownDeviceId.trim()
      const reason = shutdownReason.trim()
      const graceS = Number.parseInt(shutdownGraceS, 10)
      if (!deviceIdValue) throw new Error('Device ID is required for shutdown command.')
      if (!reason) throw new Error('Shutdown reason is required.')
      if (!Number.isFinite(graceS) || graceS <= 0 || graceS > 3600) {
        throw new Error('Shutdown grace must be between 1 and 3600 seconds.')
      }
      return api.admin.shutdownDevice(adminCred, deviceIdValue, {
        reason,
        shutdown_grace_s: graceS,
      })
    },
    onSuccess: (out) => {
      qc.invalidateQueries({ queryKey: ['device', shutdownDeviceId.trim()] })
      qc.invalidateQueries({ queryKey: ['deviceControls', shutdownDeviceId.trim()] })
      qc.invalidateQueries({ queryKey: ['devicesSummary'] })
      qc.invalidateQueries({ queryKey: ['admin', 'events'] })
      toast({
        title: 'Shutdown command queued',
        description: `Pending command(s): ${out.pending_command_count}`,
        variant: 'warning',
      })
    },
    onError: (error) => {
      toast({
        title: 'Unable to queue shutdown command',
        description: (error as Error).message,
        variant: 'error',
      })
    },
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
      { header: 'Source', accessorKey: 'source_kind', cell: (i) => <Badge variant="outline">{String(i.getValue())}</Badge> },
      { header: 'Source ID', accessorKey: 'source_id', cell: (i) => <span className="font-mono text-xs">{String(i.getValue() ?? '—')}</span> },
      { header: 'Type', accessorKey: 'alert_type' },
      { header: 'Channel', accessorKey: 'channel', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
      { header: 'Decision', accessorKey: 'decision' },
      { header: 'Delivered', accessorKey: 'delivered', cell: (i) => (i.getValue() ? <Badge variant="success">yes</Badge> : <Badge variant="destructive">no</Badge>) },
      { header: 'Reason', accessorKey: 'reason', cell: (i) => <span className="text-muted-foreground">{String(i.getValue())}</span> },
      {
        header: 'Payload',
        cell: (i) => (
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">view</summary>
            <pre className="mt-2 whitespace-pre-wrap break-words">{JSON.stringify(i.row.original.payload, null, 2)}</pre>
          </details>
        ),
      },
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

  const accessCols = React.useMemo<ColumnDef<DeviceAccessGrantOut>[]>(() => {
    return [
      { header: 'Principal', accessorKey: 'principal_email', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Role', accessorKey: 'access_role', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
      { header: 'Updated', accessorKey: 'updated_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as any)}</span> },
      {
        header: 'Action',
        cell: (i) => (
          <Button
            size="sm"
            variant="outline"
            onClick={() => deleteAccessMutation.mutate(i.row.original.principal_email)}
            disabled={deleteAccessMutation.isPending}
          >
            remove
          </Button>
        ),
      },
    ]
  }, [deleteAccessMutation])

  const fleetCols = React.useMemo<ColumnDef<FleetOut>[]>(() => {
    return [
      { header: 'Name', accessorKey: 'name' },
      { header: 'Fleet ID', accessorKey: 'id', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Channel', accessorKey: 'default_ota_channel', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
      { header: 'Devices', accessorKey: 'device_count', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Description', accessorKey: 'description', cell: (i) => <span className="text-muted-foreground">{String(i.getValue() ?? '—')}</span> },
    ]
  }, [])

  const fleetAccessCols = React.useMemo<ColumnDef<any>[]>(() => {
    return [
      { header: 'Principal', accessorKey: 'principal_email', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Role', accessorKey: 'access_role', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
      { header: 'Updated', accessorKey: 'updated_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as any)}</span> },
    ]
  }, [])

  const procedureDefinitionCols = React.useMemo<ColumnDef<DeviceProcedureDefinitionOut>[]>(() => {
    return [
      { header: 'Name', accessorKey: 'name' },
      { header: 'Timeout', accessorKey: 'timeout_s', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}s</span> },
      { header: 'Enabled', accessorKey: 'enabled', cell: (i) => (i.getValue() ? <Badge variant="success">yes</Badge> : <Badge variant="outline">no</Badge>) },
      { header: 'Created by', accessorKey: 'created_by', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Description', accessorKey: 'description', cell: (i) => <span className="text-muted-foreground">{String(i.getValue() ?? '—')}</span> },
    ]
  }, [])

  const filteredProcedureDefinitions = React.useMemo(() => {
    const q = procedureFilter.toLowerCase()
    const rows = procedureDefinitionsQ.data ?? []
    if (!q) return rows
    return rows.filter((row) => {
      const name = row.name.toLowerCase()
      const description = String(row.description ?? '').toLowerCase()
      return name.includes(q) || description.includes(q)
    })
  }, [procedureDefinitionsQ.data, procedureFilter])

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
          <a href="/settings#admin-access" className="underline">Configure an admin key in Settings</a>.
        </Callout>
      ) : keyValidating ? (
        <Callout title="Validating admin key">Checking admin access…</Callout>
      ) : keyInvalid ? (
        <Callout title="Invalid admin key" tone="warning">
          <a href="/settings#admin-access" className="underline">Update the configured key in Settings</a>.
        </Callout>
      ) : null}

      {adminAccess ? (
        <>
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
              <div className="space-y-2 lg:col-span-2">
                <Label>Owner emails (comma-separated)</Label>
                <Input
                  value={provOwners}
                  onChange={(e) => setProvOwners(e.target.value)}
                  placeholder="owner1@example.com, owner2@example.com"
                  disabled={inputsDisabled}
                />
                <div className="text-xs text-muted-foreground">
                  Optional. Grants device-level owner access at creation time.
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

          <Card id="device-access">
            <CardHeader>
              <CardTitle>Device ownership access</CardTitle>
              <CardDescription>
                Grant or revoke per-device access for non-admin users.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 lg:grid-cols-4">
                <div className="space-y-2">
                  <Label>Device ID</Label>
                  <Input
                    value={accessDeviceId}
                    onChange={(e) => setAccessDeviceId(e.target.value)}
                    placeholder="well-001"
                    disabled={inputsDisabled}
                  />
                </div>
                <div className="space-y-2 lg:col-span-2">
                  <Label>Principal email</Label>
                  <Input
                    value={accessPrincipalEmail}
                    onChange={(e) => setAccessPrincipalEmail(e.target.value)}
                    placeholder="operator@example.com"
                    disabled={inputsDisabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Role</Label>
                  <select
                    className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={accessRole}
                    onChange={(e) => setAccessRole(e.target.value as 'viewer' | 'operator' | 'owner')}
                    disabled={inputsDisabled}
                  >
                    <option value="viewer">viewer</option>
                    <option value="operator">operator</option>
                    <option value="owner">owner</option>
                  </select>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => upsertAccessMutation.mutate()}
                  disabled={inputsDisabled || upsertAccessMutation.isPending}
                >
                  {upsertAccessMutation.isPending ? 'Saving access…' : 'Grant / update access'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => qc.invalidateQueries({ queryKey: ['admin', 'deviceAccess', accessDeviceId.trim()] })}
                  disabled={inputsDisabled || !accessDeviceId.trim()}
                >
                  Refresh list
                </Button>
              </div>
              {deviceAccessQ.isError ? (
                <div className="text-sm text-destructive">Error: {(deviceAccessQ.error as Error).message}</div>
              ) : null}
              <DataTable<DeviceAccessGrantOut>
                data={deviceAccessQ.data ?? []}
                columns={accessCols}
                emptyState={accessDeviceId.trim() ? 'No access grants for this device.' : 'Enter a device ID to view access grants.'}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Admin shutdown command</CardTitle>
              <CardDescription>
                Queue a one-shot <span className="font-mono">disabled + shutdown</span> command.
                This is admin-only and still respects the agent-side shutdown guard.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 lg:grid-cols-3">
                <div className="space-y-2">
                  <Label>Device ID</Label>
                  <Input
                    value={shutdownDeviceId}
                    onChange={(e) => setShutdownDeviceId(e.target.value)}
                    placeholder="well-001"
                    disabled={inputsDisabled}
                  />
                </div>
                <div className="space-y-2 lg:col-span-2">
                  <Label>Reason</Label>
                  <Input
                    value={shutdownReason}
                    onChange={(e) => setShutdownReason(e.target.value)}
                    placeholder="seasonal intermission"
                    disabled={inputsDisabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Grace seconds</Label>
                  <Input
                    value={shutdownGraceS}
                    onChange={(e) => setShutdownGraceS(e.target.value)}
                    placeholder="30"
                    disabled={inputsDisabled}
                  />
                </div>
              </div>
              <div className="text-xs text-muted-foreground">
                Device executes OS shutdown only when <span className="font-mono">EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1</span>.
                Otherwise the command applies logical disable only.
              </div>
              <Button
                type="button"
                variant="destructive"
                onClick={() => shutdownMutation.mutate()}
                disabled={inputsDisabled || shutdownMutation.isPending}
              >
                {shutdownMutation.isPending ? 'Queueing shutdown…' : 'Queue disable + shutdown'}
              </Button>
            </CardContent>
          </Card>

          <Card id="fleet-governance">
            <CardHeader>
              <CardTitle>Fleets</CardTitle>
              <CardDescription>
                Manage fleet governance scopes, default channels, and fleet-scoped access.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 lg:grid-cols-3">
                <div className="space-y-2">
                  <Label>Fleet name</Label>
                  <Input value={fleetName} onChange={(e) => setFleetName(e.target.value)} placeholder="Pilot West" disabled={inputsDisabled} />
                </div>
                <div className="space-y-2">
                  <Label>Default OTA channel</Label>
                  <Input value={fleetDefaultChannel} onChange={(e) => setFleetDefaultChannel(e.target.value)} placeholder="stable" disabled={inputsDisabled} />
                </div>
                <div className="space-y-2 lg:col-span-3">
                  <Label>Description</Label>
                  <Input value={fleetDescription} onChange={(e) => setFleetDescription(e.target.value)} placeholder="Pilot devices for the west field cluster" disabled={inputsDisabled} />
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="outline" onClick={() => createFleetMutation.mutate()} disabled={inputsDisabled || createFleetMutation.isPending}>
                  {createFleetMutation.isPending ? 'Creating fleet…' : 'Create fleet'}
                </Button>
                <Button type="button" variant="outline" onClick={() => qc.invalidateQueries({ queryKey: ['admin', 'fleets'] })} disabled={inputsDisabled}>
                  Refresh fleets
                </Button>
              </div>
              <DataTable<FleetOut>
                data={fleetsQ.data ?? []}
                columns={fleetCols}
                emptyState="No fleets yet."
                onRowClick={(row) => setFleetSelectedId(row.id)}
              />

              <div className="grid gap-4 lg:grid-cols-3">
                <div className="space-y-2 lg:col-span-2">
                  <Label>Selected fleet ID</Label>
                  <Input value={fleetSelectedId} onChange={(e) => setFleetSelectedId(e.target.value)} placeholder="fleet UUID" disabled={inputsDisabled} />
                </div>
                <div className="space-y-2">
                  <Label>Device ID</Label>
                  <Input value={fleetDeviceId} onChange={(e) => setFleetDeviceId(e.target.value)} placeholder="well-001" disabled={inputsDisabled} />
                </div>
                <div className="space-y-2 lg:col-span-2">
                  <Label>Fleet access principal</Label>
                  <Input value={fleetAccessEmail} onChange={(e) => setFleetAccessEmail(e.target.value)} placeholder="operator@example.com" disabled={inputsDisabled} />
                </div>
                <div className="space-y-2">
                  <Label>Fleet access role</Label>
                  <select
                    className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={fleetAccessRole}
                    onChange={(e) => setFleetAccessRole(e.target.value as 'viewer' | 'operator' | 'owner')}
                    disabled={inputsDisabled}
                  >
                    <option value="viewer">viewer</option>
                    <option value="operator">operator</option>
                    <option value="owner">owner</option>
                  </select>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="outline" onClick={() => addFleetDeviceMutation.mutate()} disabled={inputsDisabled || addFleetDeviceMutation.isPending}>
                  {addFleetDeviceMutation.isPending ? 'Adding device…' : 'Add device to fleet'}
                </Button>
                <Button type="button" variant="outline" onClick={() => putFleetAccessMutation.mutate()} disabled={inputsDisabled || putFleetAccessMutation.isPending}>
                  {putFleetAccessMutation.isPending ? 'Saving access…' : 'Grant fleet access'}
                </Button>
              </div>
              <DataTable<any>
                data={fleetAccessQ.data ?? []}
                columns={fleetAccessCols}
                emptyState={fleetSelectedId.trim() ? 'No fleet access grants yet.' : 'Select or enter a fleet ID to manage access.'}
              />
            </CardContent>
          </Card>

          <div id="procedure-definitions">
          <Card>
            <CardHeader>
              <CardTitle>Procedure definitions</CardTitle>
              <CardDescription>
                Create predeclared typed procedures for device-side invocation.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Filter definitions</Label>
                <Input
                  value={procedureFilterRaw}
                  onChange={(e) => setProcedureFilterRaw(e.target.value)}
                  placeholder="capture_snapshot"
                  disabled={inputsDisabled}
                />
              </div>
              <div className="grid gap-4 lg:grid-cols-3">
                <div className="space-y-2">
                  <Label>Name</Label>
                  <Input value={procedureName} onChange={(e) => setProcedureName(e.target.value)} placeholder="capture_snapshot" disabled={inputsDisabled} />
                </div>
                <div className="space-y-2">
                  <Label>Timeout seconds</Label>
                  <Input value={procedureTimeoutS} onChange={(e) => setProcedureTimeoutS(e.target.value)} placeholder="300" disabled={inputsDisabled} />
                </div>
                <div className="space-y-2 lg:col-span-3">
                  <Label>Description</Label>
                  <Input value={procedureDescription} onChange={(e) => setProcedureDescription(e.target.value)} placeholder="Capture a diagnostic snapshot from the selected camera" disabled={inputsDisabled} />
                </div>
                <div className="space-y-2 lg:col-span-3">
                  <Label>Request schema JSON</Label>
                  <textarea className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono" value={procedureRequestSchema} onChange={(e) => setProcedureRequestSchema(e.target.value)} disabled={inputsDisabled} />
                </div>
                <div className="space-y-2 lg:col-span-3">
                  <Label>Response schema JSON</Label>
                  <textarea className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono" value={procedureResponseSchema} onChange={(e) => setProcedureResponseSchema(e.target.value)} disabled={inputsDisabled} />
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="outline" onClick={() => createProcedureDefinitionMutation.mutate()} disabled={inputsDisabled || createProcedureDefinitionMutation.isPending}>
                  {createProcedureDefinitionMutation.isPending ? 'Creating procedure…' : 'Create procedure definition'}
                </Button>
                <Button type="button" variant="outline" onClick={() => qc.invalidateQueries({ queryKey: ['admin', 'procedureDefinitions'] })} disabled={inputsDisabled}>
                  Refresh procedures
                </Button>
              </div>
              <DataTable<DeviceProcedureDefinitionOut>
                data={filteredProcedureDefinitions}
                columns={procedureDefinitionCols}
                emptyState="No procedure definitions yet."
              />
            </CardContent>
          </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Releases Workspace</CardTitle>
              <CardDescription>
                Release publishing and rollout control now live in the dedicated Releases workspace.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {!otaUpdatesEnabled ? (
                <Callout title="OTA routes disabled">
                  Enable <span className="font-mono">ENABLE_OTA_UPDATES=1</span> on the API service to use release and deployment controls.
                </Callout>
              ) : null}
              <div className="space-y-3">
                <div className="text-sm text-muted-foreground">
                  Release publishing, rollout creation, lifecycle control, and target inspection now live in the dedicated
                  Releases workspace.
                </div>
                <div className="flex flex-wrap gap-2">
                  <Link
                    to="/releases"
                    search={{ deploymentId: '', manifestId: '', targetDeviceId: '' }}
                    className="inline-flex h-10 items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-muted/40"
                  >
                    Open Releases workspace
                  </Link>
                </div>
              </div>
            </CardContent>
          </Card>
        </>
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
              {tab === 'ingestions' || tab === 'drift' ? (
                <div className="space-y-2">
                  <Label>Batch ID</Label>
                  <Input
                    value={batchIdRaw}
                    onChange={(e) => setBatchIdRaw(e.target.value)}
                    placeholder="Optional batch id…"
                    disabled={inputsDisabled}
                  />
                </div>
              ) : null}
              <div className="space-y-2">
                <Label>Status (exports tab)</Label>
                <Input
                  value={statusRaw}
                  onChange={(e) => setStatusRaw(e.target.value)}
                  placeholder="success | failed | running"
                  disabled={inputsDisabled}
                />
              </div>
              {tab === 'exports' ? (
                <div className="space-y-2">
                  <Label>Export batch ID</Label>
                  <Input
                    value={exportIdRaw}
                    onChange={(e) => setExportIdRaw(e.target.value)}
                    placeholder="Optional export batch id…"
                    disabled={inputsDisabled}
                  />
                </div>
              ) : (
              <div className="space-y-2">
                <Label>Notes</Label>
                <div className="text-xs text-muted-foreground">
                  Ingestions/drift support a device filter. Notifications support device plus delivery filters. Exports support a status filter.
                </div>
              </div>
              )}
              {tab === 'exports' ? (
                <div className="space-y-2">
                  <Label>Notes</Label>
                  <div className="text-xs text-muted-foreground">
                    Exports support status filtering plus a local export batch id filter for exact landing-state navigation.
                  </div>
                </div>
              ) : null}
              {tab === 'notifications' ? (
                <>
                  <div className="space-y-2">
                    <Label>Source kind</Label>
                    <Input
                      value={notificationSourceKindRaw}
                      onChange={(e) => setNotificationSourceKindRaw(e.target.value)}
                      placeholder="alert | device_event | deployment_event"
                      disabled={inputsDisabled}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Channel</Label>
                    <Input
                      value={notificationChannelRaw}
                      onChange={(e) => setNotificationChannelRaw(e.target.value)}
                      placeholder="webhook"
                      disabled={inputsDisabled}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Decision</Label>
                    <Input
                      value={notificationDecisionRaw}
                      onChange={(e) => setNotificationDecisionRaw(e.target.value)}
                      placeholder="delivered | blocked | filtered"
                      disabled={inputsDisabled}
                    />
                  </div>
                  <div className="flex items-center gap-3 lg:col-span-3">
                    <label className="inline-flex items-center gap-2 text-sm">
                      <Checkbox
                        checked={notificationDeliveredOnly}
                        onChange={(e) => {
                          const next = e.target.checked
                          setNotificationDeliveredOnly(next)
                          if (next) setNotificationFailedOnly(false)
                        }}
                        disabled={inputsDisabled}
                      />
                      Delivered only
                    </label>
                    <label className="inline-flex items-center gap-2 text-sm">
                      <Checkbox
                        checked={notificationFailedOnly}
                        onChange={(e) => {
                          const next = e.target.checked
                          setNotificationFailedOnly(next)
                          if (next) setNotificationDeliveredOnly(false)
                        }}
                        disabled={inputsDisabled}
                      />
                      Undelivered only
                    </label>
                  </div>
                </>
              ) : null}
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
                <div id="admin-ingestions" className="space-y-3">
                  {ingestionsQ.data ? (
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span>
                        Showing {Math.min(ingestionsQ.data.total, ingestionOffset + 1)}-{Math.min(ingestionsQ.data.total, ingestionOffset + ingestionsQ.data.items.length)} of {ingestionsQ.data.total}
                      </span>
                      <div className="flex items-center gap-2">
                        <Button variant="outline" onClick={() => setIngestionOffset((current) => Math.max(0, current - ingestionLimit))} disabled={ingestionOffset <= 0}>
                          Previous page
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => setIngestionOffset((current) => current + ingestionLimit)}
                          disabled={(ingestionsQ.data.offset + ingestionsQ.data.limit) >= ingestionsQ.data.total}
                        >
                          Next page
                        </Button>
                      </div>
                    </div>
                  ) : null}
                  <DataTable<IngestionBatchOut>
                    data={filteredIngestions}
                    columns={ingestionCols}
                    height={560}
                    enableSorting
                    initialSorting={[{ id: 'received_at', desc: true }]}
                    emptyState="No batches found."
                  />
                </div>
              ) : null}
              {tab === 'events' ? (
                <div id="admin-events" className="space-y-3">
                  <div className="grid gap-3 lg:grid-cols-3">
                    <Input
                      value={deviceRaw}
                      onChange={(e) => setDeviceRaw(e.target.value)}
                      placeholder="Optional device id filter…"
                    />
                    <Input
                      value={eventActionRaw}
                      onChange={(e) => setEventActionRaw(e.target.value)}
                      placeholder="Optional action filter…"
                    />
                    <Input
                      value={eventTargetTypeRaw}
                      onChange={(e) => setEventTargetTypeRaw(e.target.value)}
                      placeholder="Optional target type filter…"
                    />
                  </div>
                  {eventsQ.data ? (
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span>
                        Showing {Math.min(eventsQ.data.total, eventOffset + 1)}-{Math.min(eventsQ.data.total, eventOffset + eventsQ.data.items.length)} of {eventsQ.data.total}
                      </span>
                      <div className="flex items-center gap-2">
                        <Button variant="outline" onClick={() => setEventOffset((current) => Math.max(0, current - eventLimit))} disabled={eventOffset <= 0}>
                          Previous page
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => setEventOffset((current) => current + eventLimit)}
                          disabled={(eventsQ.data.offset + eventsQ.data.limit) >= eventsQ.data.total}
                        >
                          Next page
                        </Button>
                      </div>
                    </div>
                  ) : null}
                  <DataTable<AdminEventOut>
                    data={eventsQ.data?.items ?? []}
                    columns={eventCols}
                    height={560}
                    enableSorting
                    initialSorting={[{ id: 'created_at', desc: true }]}
                    emptyState="No admin events found."
                  />
                </div>
              ) : null}
              {tab === 'drift' ? (
                <div id="admin-drift" className="space-y-3">
                  {driftQ.data ? (
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span>
                        Showing {Math.min(driftQ.data.total, driftOffset + 1)}-{Math.min(driftQ.data.total, driftOffset + driftQ.data.items.length)} of {driftQ.data.total}
                      </span>
                      <div className="flex items-center gap-2">
                        <Button variant="outline" onClick={() => setDriftOffset((current) => Math.max(0, current - driftLimit))} disabled={driftOffset <= 0}>
                          Previous page
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => setDriftOffset((current) => current + driftLimit)}
                          disabled={(driftQ.data.offset + driftQ.data.limit) >= driftQ.data.total}
                        >
                          Next page
                        </Button>
                      </div>
                    </div>
                  ) : null}
                  <DataTable<DriftEventOut>
                    data={filteredDrift}
                    columns={driftCols}
                    height={560}
                    enableSorting
                    initialSorting={[{ id: 'created_at', desc: true }]}
                    emptyState="No drift events found."
                  />
                </div>
              ) : null}
              {tab === 'notifications' ? (
                <div id="admin-notifications" className="space-y-3">
                  {notificationsQ.data ? (
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span>
                        Showing {Math.min(notificationsQ.data.total, notificationOffset + 1)}-{Math.min(notificationsQ.data.total, notificationOffset + notificationsQ.data.items.length)} of {notificationsQ.data.total}
                      </span>
                      <div className="flex items-center gap-2">
                        <Button variant="outline" onClick={() => setNotificationOffset((current) => Math.max(0, current - notificationLimit))} disabled={notificationOffset <= 0}>
                          Previous page
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => setNotificationOffset((current) => current + notificationLimit)}
                          disabled={(notificationsQ.data.offset + notificationsQ.data.limit) >= notificationsQ.data.total}
                        >
                          Next page
                        </Button>
                      </div>
                    </div>
                  ) : null}
                  <DataTable<NotificationEventOut>
                    data={notificationsQ.data?.items ?? []}
                    columns={notificationCols}
                    height={560}
                    enableSorting
                    initialSorting={[{ id: 'created_at', desc: true }]}
                    emptyState="No notification events found."
                  />
                </div>
              ) : null}
              {tab === 'exports' ? (
                <div id="admin-exports" className="space-y-3">
                  {exportsQ.data ? (
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span>
                        Showing {filteredExports.length ? Math.min(exportsQ.data.total, exportOffset + 1) : 0}-{Math.min(exportsQ.data.total, exportOffset + filteredExports.length)} of {exportsQ.data.total}
                      </span>
                      <div className="flex items-center gap-2">
                        <Button variant="outline" onClick={() => setExportOffset((current) => Math.max(0, current - exportLimit))} disabled={exportOffset <= 0}>
                          Previous page
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => setExportOffset((current) => current + exportLimit)}
                          disabled={(exportsQ.data.offset + exportsQ.data.limit) >= exportsQ.data.total}
                        >
                          Next page
                        </Button>
                      </div>
                    </div>
                  ) : null}
                  <DataTable<ExportBatchOut>
                    data={filteredExports}
                    columns={exportCols}
                    height={560}
                    enableSorting
                    initialSorting={[{ id: 'started_at', desc: true }]}
                    emptyState="No export batches found."
                  />
                </div>
              ) : null}
            </CardContent>
          </Card>
        </>
      ) : null}

    </Page>
  )
}
