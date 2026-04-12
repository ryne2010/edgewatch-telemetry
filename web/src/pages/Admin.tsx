import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link } from '@tanstack/react-router'
import { useDebouncedValue } from '@tanstack/react-pacer/debouncer'
import {
  api,
  type AdminEventOut,
  type DeploymentDetailOut,
  type DeviceAccessGrantOut,
  type DriftEventOut,
  type ExportBatchOut,
  type IngestionBatchOut,
  type NotificationEventOut,
  type ReleaseManifestOut,
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
  const [manifestGitTag, setManifestGitTag] = React.useState('')
  const [manifestCommitSha, setManifestCommitSha] = React.useState('')
  const [manifestSignature, setManifestSignature] = React.useState('')
  const [manifestSignatureKeyId, setManifestSignatureKeyId] = React.useState('ops-key-1')
  const [manifestConstraints, setManifestConstraints] = React.useState('{}')
  const [manifestStatus, setManifestStatus] = React.useState('active')
  const [deploymentManifestId, setDeploymentManifestId] = React.useState('')
  const [deploymentSelectorMode, setDeploymentSelectorMode] = React.useState<
    'all' | 'cohort' | 'labels' | 'explicit_ids'
  >('all')
  const [deploymentSelectorCohort, setDeploymentSelectorCohort] = React.useState('')
  const [deploymentSelectorLabels, setDeploymentSelectorLabels] = React.useState('{}')
  const [deploymentSelectorIds, setDeploymentSelectorIds] = React.useState('')
  const [deploymentRolloutStages, setDeploymentRolloutStages] = React.useState('1,10,50,100')
  const [deploymentFailureRateThreshold, setDeploymentFailureRateThreshold] = React.useState('0.2')
  const [deploymentNoQuorumTimeoutS, setDeploymentNoQuorumTimeoutS] = React.useState('1800')
  const [deploymentHealthTimeoutS, setDeploymentHealthTimeoutS] = React.useState('300')
  const [deploymentCommandTtlS, setDeploymentCommandTtlS] = React.useState(String(180 * 24 * 3600))
  const [deploymentPowerGuardRequired, setDeploymentPowerGuardRequired] = React.useState(true)
  const [deploymentRollbackToTag, setDeploymentRollbackToTag] = React.useState('')
  const [deploymentLookupId, setDeploymentLookupId] = React.useState('')
  const [deploymentAbortReason, setDeploymentAbortReason] = React.useState('manual abort')

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

  const releaseManifestsQ = useQuery({
    queryKey: ['admin', 'releaseManifests'],
    queryFn: () => api.admin.releaseManifests(adminCred, { limit: 200 }),
    enabled: adminAccess && otaUpdatesEnabled,
  })

  const deploymentDetailQ = useQuery({
    queryKey: ['admin', 'deploymentDetail', deploymentLookupId.trim()],
    queryFn: () => api.admin.deployment(adminCred, deploymentLookupId.trim()),
    enabled: adminAccess && otaUpdatesEnabled && Boolean(deploymentLookupId.trim()),
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

  const createManifestMutation = useMutation({
    mutationFn: async () => {
      const gitTag = manifestGitTag.trim()
      const commitSha = manifestCommitSha.trim()
      const signature = manifestSignature.trim()
      const signatureKeyId = manifestSignatureKeyId.trim()
      if (!gitTag) throw new Error('Git tag is required.')
      if (!commitSha) throw new Error('Commit SHA is required.')
      if (!signature) throw new Error('Signature is required.')
      if (!signatureKeyId) throw new Error('Signature key id is required.')
      let constraints: Record<string, unknown> = {}
      if (manifestConstraints.trim()) {
        try {
          const parsed = JSON.parse(manifestConstraints)
          if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
            throw new Error('Manifest constraints must be a JSON object.')
          }
          constraints = parsed as Record<string, unknown>
        } catch {
          throw new Error('Manifest constraints must be valid JSON object.')
        }
      }
      return api.admin.createReleaseManifest(adminCred, {
        git_tag: gitTag,
        commit_sha: commitSha,
        signature,
        signature_key_id: signatureKeyId,
        constraints,
        status: manifestStatus.trim() || 'active',
      })
    },
    onSuccess: (manifest) => {
      qc.invalidateQueries({ queryKey: ['admin', 'releaseManifests'] })
      setDeploymentManifestId((prev) => prev || manifest.id)
      toast({
        title: 'Release manifest created',
        description: `${manifest.git_tag} (${manifest.id.slice(0, 8)})`,
        variant: 'success',
      })
    },
    onError: (error) => {
      toast({
        title: 'Unable to create release manifest',
        description: (error as Error).message,
        variant: 'error',
      })
    },
  })

  const createDeploymentMutation = useMutation({
    mutationFn: async () => {
      const manifestId = deploymentManifestId.trim()
      if (!manifestId) throw new Error('Manifest ID is required.')

      const targetSelector: {
        mode: 'all' | 'cohort' | 'labels' | 'explicit_ids'
        cohort?: string
        labels?: Record<string, string>
        device_ids?: string[]
      } = { mode: deploymentSelectorMode }
      if (deploymentSelectorMode === 'cohort') {
        const cohort = deploymentSelectorCohort.trim()
        if (!cohort) throw new Error('Cohort is required for cohort selector.')
        targetSelector.cohort = cohort
      } else if (deploymentSelectorMode === 'labels') {
        try {
          const parsed = JSON.parse(deploymentSelectorLabels)
          if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
            throw new Error('Labels must be a JSON object.')
          }
          const labels = Object.fromEntries(
            Object.entries(parsed).map(([k, v]) => [String(k).trim(), String(v).trim()]),
          )
          if (!Object.keys(labels).length) throw new Error('At least one label is required.')
          targetSelector.labels = labels
        } catch {
          throw new Error('Labels must be valid JSON object.')
        }
      } else if (deploymentSelectorMode === 'explicit_ids') {
        const ids = Array.from(
          new Set(
            deploymentSelectorIds
              .split(',')
              .map((v) => v.trim())
              .filter(Boolean),
          ),
        )
        if (!ids.length) throw new Error('At least one device ID is required for explicit selector.')
        targetSelector.device_ids = ids
      }

      const rolloutStages = Array.from(
        new Set(
          deploymentRolloutStages
            .split(',')
            .map((v) => Number.parseInt(v.trim(), 10))
            .filter((v) => Number.isFinite(v) && v > 0 && v <= 100),
        ),
      ).sort((a, b) => a - b)
      if (!rolloutStages.length) throw new Error('Rollout stages must include at least one value 1..100.')

      const failureRateThreshold = Number.parseFloat(deploymentFailureRateThreshold)
      if (!Number.isFinite(failureRateThreshold) || failureRateThreshold < 0 || failureRateThreshold > 1) {
        throw new Error('Failure threshold must be between 0 and 1.')
      }
      const noQuorumTimeoutS = Number.parseInt(deploymentNoQuorumTimeoutS, 10)
      if (!Number.isFinite(noQuorumTimeoutS) || noQuorumTimeoutS < 60) {
        throw new Error('No-quorum timeout must be >= 60.')
      }
      const healthTimeoutS = Number.parseInt(deploymentHealthTimeoutS, 10)
      if (!Number.isFinite(healthTimeoutS) || healthTimeoutS < 10) {
        throw new Error('Health timeout must be >= 10.')
      }
      const commandTtlS = Number.parseInt(deploymentCommandTtlS, 10)
      if (!Number.isFinite(commandTtlS) || commandTtlS < 60) {
        throw new Error('Command TTL must be >= 60.')
      }

      return api.admin.createDeployment(adminCred, {
        manifest_id: manifestId,
        target_selector: targetSelector,
        rollout_stages_pct: rolloutStages,
        failure_rate_threshold: failureRateThreshold,
        no_quorum_timeout_s: noQuorumTimeoutS,
        health_timeout_s: healthTimeoutS,
        command_ttl_s: commandTtlS,
        power_guard_required: deploymentPowerGuardRequired,
        rollback_to_tag: deploymentRollbackToTag.trim() || null,
      })
    },
    onSuccess: (deployment) => {
      setDeploymentLookupId(deployment.id)
      qc.invalidateQueries({ queryKey: ['admin', 'deploymentDetail', deployment.id] })
      qc.invalidateQueries({ queryKey: ['admin', 'events'] })
      toast({
        title: 'Deployment created',
        description: `ID ${deployment.id.slice(0, 8)} stage ${deployment.stage}`,
        variant: 'success',
      })
    },
    onError: (error) => {
      toast({
        title: 'Unable to create deployment',
        description: (error as Error).message,
        variant: 'error',
      })
    },
  })

  const deploymentActionMutation = useMutation({
    mutationFn: async (action: 'pause' | 'resume' | 'abort') => {
      const deploymentId = deploymentLookupId.trim()
      if (!deploymentId) throw new Error('Deployment ID is required.')
      if (action === 'pause') return api.admin.pauseDeployment(adminCred, deploymentId)
      if (action === 'resume') return api.admin.resumeDeployment(adminCred, deploymentId)
      return api.admin.abortDeployment(adminCred, deploymentId, { reason: deploymentAbortReason.trim() || undefined })
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['admin', 'deploymentDetail', result.id] })
      qc.invalidateQueries({ queryKey: ['admin', 'events'] })
      toast({
        title: 'Deployment updated',
        description: `${result.id.slice(0, 8)} → ${result.status}`,
        variant: result.status === 'aborted' ? 'warning' : 'success',
      })
    },
    onError: (error) => {
      toast({
        title: 'Unable to update deployment',
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

          <Card>
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

          <Card>
            <CardHeader>
              <CardTitle>OTA releases and deployments</CardTitle>
              <CardDescription>
                Publish signed release manifests and manage staged fleet rollouts.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {!otaUpdatesEnabled ? (
                <Callout title="OTA routes disabled">
                  Enable <span className="font-mono">ENABLE_OTA_UPDATES=1</span> on the API service to use
                  manifest/deployment controls.
                </Callout>
              ) : null}

              <div className="grid gap-4 lg:grid-cols-2">
                <div className="space-y-2">
                  <Label>Git tag</Label>
                  <Input
                    value={manifestGitTag}
                    onChange={(e) => setManifestGitTag(e.target.value)}
                    placeholder="v1.4.0"
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Commit SHA</Label>
                  <Input
                    value={manifestCommitSha}
                    onChange={(e) => setManifestCommitSha(e.target.value)}
                    placeholder="abc123..."
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Signature key ID</Label>
                  <Input
                    value={manifestSignatureKeyId}
                    onChange={(e) => setManifestSignatureKeyId(e.target.value)}
                    placeholder="ops-key-1"
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Status</Label>
                  <Input
                    value={manifestStatus}
                    onChange={(e) => setManifestStatus(e.target.value)}
                    placeholder="active"
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  />
                </div>
                <div className="space-y-2 lg:col-span-2">
                  <Label>Signature</Label>
                  <Input
                    value={manifestSignature}
                    onChange={(e) => setManifestSignature(e.target.value)}
                    placeholder="base64-signature"
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  />
                </div>
                <div className="space-y-2 lg:col-span-2">
                  <Label>Constraints JSON</Label>
                  <textarea
                    className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                    value={manifestConstraints}
                    onChange={(e) => setManifestConstraints(e.target.value)}
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  />
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => createManifestMutation.mutate()}
                  disabled={inputsDisabled || !otaUpdatesEnabled || createManifestMutation.isPending}
                >
                  {createManifestMutation.isPending ? 'Creating manifest…' : 'Create manifest'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => qc.invalidateQueries({ queryKey: ['admin', 'releaseManifests'] })}
                  disabled={inputsDisabled || !otaUpdatesEnabled}
                >
                  Refresh manifests
                </Button>
              </div>

              <div className="space-y-2">
                <Label>Manifests</Label>
                {releaseManifestsQ.isError ? (
                  <div className="text-sm text-destructive">Error: {(releaseManifestsQ.error as Error).message}</div>
                ) : null}
                {(releaseManifestsQ.data ?? []).length === 0 ? (
                  <div className="text-sm text-muted-foreground">No manifests found.</div>
                ) : (
                  <div className="max-h-56 overflow-auto rounded-md border">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-muted/40">
                        <tr>
                          <th className="px-2 py-2">Tag</th>
                          <th className="px-2 py-2">Manifest ID</th>
                          <th className="px-2 py-2">Status</th>
                          <th className="px-2 py-2">Created</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(releaseManifestsQ.data ?? []).map((row: ReleaseManifestOut) => (
                          <tr
                            key={row.id}
                            className="cursor-pointer border-t hover:bg-muted/20"
                            onClick={() => setDeploymentManifestId(row.id)}
                          >
                            <td className="px-2 py-2 font-mono">{row.git_tag}</td>
                            <td className="px-2 py-2 font-mono">{row.id}</td>
                            <td className="px-2 py-2">
                              <Badge variant="secondary">{row.status}</Badge>
                            </td>
                            <td className="px-2 py-2 text-muted-foreground">{fmtDateTime(row.created_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <div className="grid gap-4 lg:grid-cols-3">
                <div className="space-y-2 lg:col-span-2">
                  <Label>Manifest ID</Label>
                  <Input
                    value={deploymentManifestId}
                    onChange={(e) => setDeploymentManifestId(e.target.value)}
                    placeholder="manifest UUID"
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Selector mode</Label>
                  <select
                    className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={deploymentSelectorMode}
                    onChange={(e) =>
                      setDeploymentSelectorMode(
                        e.target.value as 'all' | 'cohort' | 'labels' | 'explicit_ids',
                      )
                    }
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  >
                    <option value="all">all</option>
                    <option value="cohort">cohort</option>
                    <option value="labels">labels</option>
                    <option value="explicit_ids">explicit_ids</option>
                  </select>
                </div>
                {deploymentSelectorMode === 'cohort' ? (
                  <div className="space-y-2">
                    <Label>Cohort</Label>
                    <Input
                      value={deploymentSelectorCohort}
                      onChange={(e) => setDeploymentSelectorCohort(e.target.value)}
                      placeholder="pilot-west"
                      disabled={inputsDisabled || !otaUpdatesEnabled}
                    />
                  </div>
                ) : null}
                {deploymentSelectorMode === 'labels' ? (
                  <div className="space-y-2 lg:col-span-2">
                    <Label>Labels JSON</Label>
                    <textarea
                      className="min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                      value={deploymentSelectorLabels}
                      onChange={(e) => setDeploymentSelectorLabels(e.target.value)}
                      disabled={inputsDisabled || !otaUpdatesEnabled}
                    />
                  </div>
                ) : null}
                {deploymentSelectorMode === 'explicit_ids' ? (
                  <div className="space-y-2 lg:col-span-2">
                    <Label>Device IDs (comma-separated)</Label>
                    <Input
                      value={deploymentSelectorIds}
                      onChange={(e) => setDeploymentSelectorIds(e.target.value)}
                      placeholder="well-001, well-002"
                      disabled={inputsDisabled || !otaUpdatesEnabled}
                    />
                  </div>
                ) : null}
                <div className="space-y-2">
                  <Label>Rollout stages</Label>
                  <Input
                    value={deploymentRolloutStages}
                    onChange={(e) => setDeploymentRolloutStages(e.target.value)}
                    placeholder="1,10,50,100"
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Failure threshold</Label>
                  <Input
                    value={deploymentFailureRateThreshold}
                    onChange={(e) => setDeploymentFailureRateThreshold(e.target.value)}
                    placeholder="0.2"
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label>No-quorum timeout (s)</Label>
                  <Input
                    value={deploymentNoQuorumTimeoutS}
                    onChange={(e) => setDeploymentNoQuorumTimeoutS(e.target.value)}
                    placeholder="1800"
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Health timeout (s)</Label>
                  <Input
                    value={deploymentHealthTimeoutS}
                    onChange={(e) => setDeploymentHealthTimeoutS(e.target.value)}
                    placeholder="300"
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Command TTL (s)</Label>
                  <Input
                    value={deploymentCommandTtlS}
                    onChange={(e) => setDeploymentCommandTtlS(e.target.value)}
                    placeholder="15552000"
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Rollback tag (optional)</Label>
                  <Input
                    value={deploymentRollbackToTag}
                    onChange={(e) => setDeploymentRollbackToTag(e.target.value)}
                    placeholder="v1.3.9"
                    disabled={inputsDisabled || !otaUpdatesEnabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Power guard required</Label>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      checked={deploymentPowerGuardRequired}
                      onChange={(e) => setDeploymentPowerGuardRequired(e.target.checked)}
                      disabled={inputsDisabled || !otaUpdatesEnabled}
                    />
                    <span className="text-sm text-muted-foreground">defer when power is unstable</span>
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  onClick={() => createDeploymentMutation.mutate()}
                  disabled={inputsDisabled || !otaUpdatesEnabled || createDeploymentMutation.isPending}
                >
                  {createDeploymentMutation.isPending ? 'Creating deployment…' : 'Create deployment'}
                </Button>
                <Input
                  value={deploymentLookupId}
                  onChange={(e) => setDeploymentLookupId(e.target.value)}
                  placeholder="deployment UUID"
                  disabled={inputsDisabled || !otaUpdatesEnabled}
                />
                <Button
                  type="button"
                  variant="outline"
                  onClick={() =>
                    qc.invalidateQueries({
                      queryKey: ['admin', 'deploymentDetail', deploymentLookupId.trim()],
                    })
                  }
                  disabled={inputsDisabled || !otaUpdatesEnabled || !deploymentLookupId.trim()}
                >
                  Refresh deployment
                </Button>
              </div>

              {deploymentDetailQ.isError ? (
                <div className="text-sm text-destructive">
                  Error: {(deploymentDetailQ.error as Error).message}
                </div>
              ) : null}
              {deploymentDetailQ.data ? (
                <div className="space-y-3 rounded-md border p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{deploymentDetailQ.data.status}</Badge>
                    <span className="font-mono text-xs">stage {deploymentDetailQ.data.stage}</span>
                    <span className="font-mono text-xs">targets {deploymentDetailQ.data.total_targets}</span>
                    <span className="font-mono text-xs">healthy {deploymentDetailQ.data.healthy_targets}</span>
                    <span className="font-mono text-xs">failed {deploymentDetailQ.data.failed_targets}</span>
                    <span className="font-mono text-xs">deferred {deploymentDetailQ.data.deferred_targets}</span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Deployment: <span className="font-mono">{deploymentDetailQ.data.id}</span>
                    {' · '}
                    Manifest tag: <span className="font-mono">{deploymentDetailQ.data.manifest.git_tag}</span>
                    {' · '}
                    Updated: <span className="font-mono">{fmtDateTime(deploymentDetailQ.data.updated_at)}</span>
                  </div>
                  {deploymentDetailQ.data.halt_reason ? (
                    <div className="text-xs text-destructive">
                      Halt reason: {deploymentDetailQ.data.halt_reason}
                    </div>
                  ) : null}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => deploymentActionMutation.mutate('pause')}
                      disabled={
                        inputsDisabled ||
                        !otaUpdatesEnabled ||
                        deploymentActionMutation.isPending ||
                        deploymentDetailQ.data.status !== 'active'
                      }
                    >
                      Pause
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => deploymentActionMutation.mutate('resume')}
                      disabled={
                        inputsDisabled ||
                        !otaUpdatesEnabled ||
                        deploymentActionMutation.isPending ||
                        deploymentDetailQ.data.status !== 'paused'
                      }
                    >
                      Resume
                    </Button>
                    <Input
                      value={deploymentAbortReason}
                      onChange={(e) => setDeploymentAbortReason(e.target.value)}
                      placeholder="abort reason"
                      disabled={inputsDisabled || !otaUpdatesEnabled}
                    />
                    <Button
                      type="button"
                      variant="destructive"
                      onClick={() => deploymentActionMutation.mutate('abort')}
                      disabled={
                        inputsDisabled ||
                        !otaUpdatesEnabled ||
                        deploymentActionMutation.isPending ||
                        deploymentDetailQ.data.status === 'aborted' ||
                        deploymentDetailQ.data.status === 'completed'
                      }
                    >
                      Abort
                    </Button>
                  </div>
                  <details className="text-xs text-muted-foreground">
                    <summary className="cursor-pointer">Recent deployment events</summary>
                    <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words">
                      {JSON.stringify(
                        (deploymentDetailQ.data as DeploymentDetailOut).events.slice(0, 30),
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </div>
              ) : null}
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
