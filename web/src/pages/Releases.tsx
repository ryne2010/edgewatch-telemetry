import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link, useSearch } from '@tanstack/react-router'
import {
  api,
  type DeploymentDetailOut,
  type DeploymentOut,
  type DeploymentTargetOut,
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
  DataTable,
  Input,
  Label,
  Page,
  useToast,
} from '../ui-kit'
import { fmtDateTime } from '../utils/format'
import { adminAccessHint } from '../utils/adminAuth'

function statusVariant(status: string): 'success' | 'warning' | 'destructive' | 'secondary' {
  const normalized = status.trim().toLowerCase()
  if (normalized === 'active' || normalized === 'healthy' || normalized === 'completed') return 'success'
  if (normalized === 'paused' || normalized === 'deferred' || normalized === 'draft') return 'warning'
  if (normalized === 'failed' || normalized === 'aborted' || normalized === 'halted' || normalized === 'retired') {
    return 'destructive'
  }
  return 'secondary'
}

function Callout(props: { title: string; children: React.ReactNode; tone?: 'default' | 'warning' }) {
  const warning = props.tone === 'warning'
  return (
    <div className={warning ? 'rounded-lg border border-destructive/60 bg-destructive/10 p-4 shadow-sm' : 'rounded-lg border bg-muted/30 p-4'}>
      <div className={warning ? 'text-sm font-semibold text-destructive' : 'text-sm font-medium'}>{props.title}</div>
      <div className={warning ? 'mt-1 text-sm text-foreground' : 'mt-1 text-sm text-muted-foreground'}>{props.children}</div>
    </div>
  )
}

export function ReleasesPage() {
  const routeSearch = useSearch({ from: '/releases' })
  const { adminKey } = useAppSettings()
  const { toast } = useToast()
  const qc = useQueryClient()
  const [manifestFilterStatus, setManifestFilterStatus] = React.useState('active')
  const [selectedManifestId, setSelectedManifestId] = React.useState('')
  const [manifestGitTag, setManifestGitTag] = React.useState('')
  const [manifestCommitSha, setManifestCommitSha] = React.useState('')
  const [manifestUpdateType, setManifestUpdateType] = React.useState<'application_bundle' | 'asset_bundle' | 'system_image'>('application_bundle')
  const [manifestArtifactUri, setManifestArtifactUri] = React.useState('')
  const [manifestArtifactSize, setManifestArtifactSize] = React.useState('1024')
  const [manifestArtifactSha256, setManifestArtifactSha256] = React.useState('')
  const [manifestArtifactSignature, setManifestArtifactSignature] = React.useState('')
  const [manifestArtifactSignatureScheme, setManifestArtifactSignatureScheme] = React.useState<'none' | 'openssl_rsa_sha256'>('none')
  const [manifestCompatibility, setManifestCompatibility] = React.useState('{}')
  const [manifestSignature, setManifestSignature] = React.useState('')
  const [manifestSignatureKeyId, setManifestSignatureKeyId] = React.useState('ops-key-1')
  const [manifestConstraints, setManifestConstraints] = React.useState('{}')
  const [manifestStatus, setManifestStatus] = React.useState('active')
  const [recentDeploymentStatus, setRecentDeploymentStatus] = React.useState('')
  const [recentDeploymentChannel, setRecentDeploymentChannel] = React.useState('')
  const [deploymentLookupId, setDeploymentLookupId] = React.useState('')
  const [deploymentAbortReason, setDeploymentAbortReason] = React.useState('manual abort')
  const [deploymentManifestId, setDeploymentManifestId] = React.useState('')
  const [deploymentSelectorMode, setDeploymentSelectorMode] = React.useState<'all' | 'cohort' | 'labels' | 'explicit_ids' | 'channel'>('all')
  const [deploymentSelectorCohort, setDeploymentSelectorCohort] = React.useState('')
  const [deploymentSelectorChannel, setDeploymentSelectorChannel] = React.useState('')
  const [deploymentSelectorLabels, setDeploymentSelectorLabels] = React.useState('{}')
  const [deploymentSelectorIds, setDeploymentSelectorIds] = React.useState('')
  const [deploymentRolloutStages, setDeploymentRolloutStages] = React.useState('1,10,50,100')
  const [deploymentFailureRateThreshold, setDeploymentFailureRateThreshold] = React.useState('0.2')
  const [deploymentNoQuorumTimeoutS, setDeploymentNoQuorumTimeoutS] = React.useState('1800')
  const [deploymentStageTimeoutS, setDeploymentStageTimeoutS] = React.useState('1800')
  const [deploymentDeferRateThreshold, setDeploymentDeferRateThreshold] = React.useState('0.5')
  const [deploymentHealthTimeoutS, setDeploymentHealthTimeoutS] = React.useState('300')
  const [deploymentCommandTtlS, setDeploymentCommandTtlS] = React.useState(String(180 * 24 * 3600))
  const [deploymentPowerGuardRequired, setDeploymentPowerGuardRequired] = React.useState(true)
  const [deploymentRollbackToTag, setDeploymentRollbackToTag] = React.useState('')
  const [deploymentTargetStatusFilter, setDeploymentTargetStatusFilter] = React.useState('')
  const [deploymentTargetSearch, setDeploymentTargetSearch] = React.useState('')
  const [deploymentTargetOffset, setDeploymentTargetOffset] = React.useState(0)
  const [deploymentTargetLimit, setDeploymentTargetLimit] = React.useState('100')

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
  const { adminAccess, adminCred } = useAdminAccess({
    adminEnabled,
    adminAuthMode,
    adminKey,
  })
  const inputsDisabled = !adminAccess

  const manifestsQ = useQuery({
    queryKey: ['admin', 'releaseManifests', manifestFilterStatus.trim()],
    queryFn: () =>
      api.admin.releaseManifests(adminCred, {
        limit: 200,
        status: manifestFilterStatus.trim() || undefined,
      }),
    enabled: adminAccess && otaUpdatesEnabled,
  })

  const deploymentsQ = useQuery({
    queryKey: ['admin', 'deployments', recentDeploymentStatus.trim(), recentDeploymentChannel.trim()],
    queryFn: () =>
      api.admin.deployments(adminCred, {
        limit: 100,
        status: recentDeploymentStatus.trim() || undefined,
        selector_channel: recentDeploymentChannel.trim() || undefined,
      }),
    enabled: adminAccess && otaUpdatesEnabled,
  })

  const deploymentDetailQ = useQuery({
    queryKey: ['admin', 'deploymentDetail', deploymentLookupId.trim()],
    queryFn: () => api.admin.deployment(adminCred, deploymentLookupId.trim()),
    enabled: adminAccess && otaUpdatesEnabled && Boolean(deploymentLookupId.trim()),
  })

  const deploymentTargetsQ = useQuery({
    queryKey: [
      'admin',
      'deploymentTargets',
      deploymentLookupId.trim(),
      deploymentTargetStatusFilter.trim(),
      deploymentTargetSearch.trim(),
      deploymentTargetLimit,
      deploymentTargetOffset,
    ],
    queryFn: () =>
      api.admin.deploymentTargets(adminCred, deploymentLookupId.trim(), {
        status: deploymentTargetStatusFilter.trim() || undefined,
        q: deploymentTargetSearch.trim() || undefined,
        limit: Math.max(1, Number.parseInt(deploymentTargetLimit, 10) || 100),
        offset: deploymentTargetOffset,
      }),
    enabled: adminAccess && otaUpdatesEnabled && Boolean(deploymentLookupId.trim()),
  })

  const deploymentTargetPage = React.useMemo(() => {
    const total = deploymentTargetsQ.data?.total ?? 0
    const limit = deploymentTargetsQ.data?.limit ?? Math.max(1, Number.parseInt(deploymentTargetLimit, 10) || 100)
    const offset = deploymentTargetsQ.data?.offset ?? deploymentTargetOffset
    const start = total === 0 ? 0 : offset + 1
    const end = Math.min(total, offset + (deploymentTargetsQ.data?.items.length ?? limit))
    return { total, limit, offset, start, end }
  }, [deploymentTargetLimit, deploymentTargetOffset, deploymentTargetsQ.data])

  React.useEffect(() => {
    setDeploymentTargetOffset(0)
  }, [deploymentLookupId, deploymentTargetStatusFilter, deploymentTargetSearch, deploymentTargetLimit])

  React.useEffect(() => {
    if (routeSearch.deploymentId?.trim()) setDeploymentLookupId(routeSearch.deploymentId.trim())
    if (routeSearch.manifestId?.trim()) {
      setSelectedManifestId(routeSearch.manifestId.trim())
      setDeploymentManifestId((current) => current || routeSearch.manifestId.trim())
    }
    if (routeSearch.targetDeviceId?.trim()) {
      setDeploymentTargetSearch(routeSearch.targetDeviceId.trim())
    }
  }, [routeSearch.deploymentId, routeSearch.manifestId, routeSearch.targetDeviceId])

  const selectedManifest = React.useMemo(
    () => (manifestsQ.data ?? []).find((manifest) => manifest.id === selectedManifestId) ?? null,
    [manifestsQ.data, selectedManifestId],
  )

  React.useEffect(() => {
    if (!selectedManifest) return
    setDeploymentManifestId((current) => current || selectedManifest.id)
  }, [selectedManifest])

  const updateManifestStatusMutation = useMutation({
    mutationFn: async (args: { manifestId: string; status: string }) => {
      const manifestId = args.manifestId.trim()
      const status = args.status.trim()
      if (!manifestId) throw new Error('Manifest ID is required.')
      if (!status) throw new Error('Manifest status is required.')
      return api.admin.updateReleaseManifest(adminCred, manifestId, { status })
    },
    onSuccess: (manifest) => {
      qc.invalidateQueries({ queryKey: ['admin', 'releaseManifests'] })
      qc.invalidateQueries({ queryKey: ['admin', 'deployments'] })
      toast({
        title: 'Manifest updated',
        description: `${manifest.git_tag} → ${manifest.status}`,
        variant: 'success',
      })
    },
    onError: (error) => {
      toast({
        title: 'Unable to update manifest',
        description: (error as Error).message,
        variant: 'error',
      })
    },
  })

  const createManifestMutation = useMutation({
    mutationFn: async () => {
      const gitTag = manifestGitTag.trim()
      const commitSha = manifestCommitSha.trim()
      const artifactUri = manifestArtifactUri.trim()
      const artifactSize = Number.parseInt(manifestArtifactSize, 10)
      const artifactSha256 = manifestArtifactSha256.trim()
      const signature = manifestSignature.trim()
      const signatureKeyId = manifestSignatureKeyId.trim()
      if (!gitTag) throw new Error('Git tag is required.')
      if (!commitSha) throw new Error('Commit SHA is required.')
      if (!artifactUri) throw new Error('Artifact URI is required.')
      if (!Number.isFinite(artifactSize) || artifactSize <= 0) throw new Error('Artifact size must be a positive number.')
      if (artifactSha256.length !== 64) throw new Error('Artifact SHA256 must be 64 characters.')
      if (!signature) throw new Error('Signature is required.')
      if (!signatureKeyId) throw new Error('Signature key id is required.')
      let constraints: Record<string, unknown> = {}
      let compatibility: Record<string, unknown> = {}
      if (manifestConstraints.trim()) {
        try {
          const parsed = JSON.parse(manifestConstraints)
          if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
          constraints = parsed as Record<string, unknown>
        } catch {
          throw new Error('Manifest constraints must be valid JSON object.')
        }
      }
      if (manifestCompatibility.trim()) {
        try {
          const parsed = JSON.parse(manifestCompatibility)
          if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
          compatibility = parsed as Record<string, unknown>
        } catch {
          throw new Error('Manifest compatibility must be valid JSON object.')
        }
      }
      return api.admin.createReleaseManifest(adminCred, {
        git_tag: gitTag,
        commit_sha: commitSha,
        update_type: manifestUpdateType,
        artifact_uri: artifactUri,
        artifact_size: artifactSize,
        artifact_sha256: artifactSha256,
        artifact_signature: manifestArtifactSignature.trim(),
        artifact_signature_scheme: manifestArtifactSignatureScheme,
        compatibility,
        signature,
        signature_key_id: signatureKeyId,
        constraints,
        status: manifestStatus.trim() || 'active',
      })
    },
    onSuccess: (manifest) => {
      qc.invalidateQueries({ queryKey: ['admin', 'releaseManifests'] })
      setSelectedManifestId(manifest.id)
      setDeploymentManifestId(manifest.id)
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
        mode: 'all' | 'cohort' | 'labels' | 'explicit_ids' | 'channel'
        cohort?: string
        channel?: string
        labels?: Record<string, string>
        device_ids?: string[]
      } = { mode: deploymentSelectorMode }
      if (deploymentSelectorMode === 'cohort') {
        const cohort = deploymentSelectorCohort.trim()
        if (!cohort) throw new Error('Cohort is required for cohort selector.')
        targetSelector.cohort = cohort
      } else if (deploymentSelectorMode === 'channel') {
        const channel = deploymentSelectorChannel.trim()
        if (!channel) throw new Error('Channel is required for channel selector.')
        targetSelector.channel = channel
      } else if (deploymentSelectorMode === 'labels') {
        try {
          const parsed = JSON.parse(deploymentSelectorLabels)
          if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
          const labels = Object.fromEntries(Object.entries(parsed).map(([k, v]) => [String(k).trim(), String(v).trim()]))
          if (!Object.keys(labels).length) throw new Error()
          targetSelector.labels = labels
        } catch {
          throw new Error('Labels must be valid JSON object.')
        }
      } else if (deploymentSelectorMode === 'explicit_ids') {
        const ids = Array.from(new Set(deploymentSelectorIds.split(',').map((v) => v.trim()).filter(Boolean)))
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
      const noQuorumTimeoutS = Number.parseInt(deploymentNoQuorumTimeoutS, 10)
      const stageTimeoutS = Number.parseInt(deploymentStageTimeoutS, 10)
      const deferRateThreshold = Number.parseFloat(deploymentDeferRateThreshold)
      const healthTimeoutS = Number.parseInt(deploymentHealthTimeoutS, 10)
      const commandTtlS = Number.parseInt(deploymentCommandTtlS, 10)
      if (!Number.isFinite(failureRateThreshold) || failureRateThreshold < 0 || failureRateThreshold > 1) throw new Error('Failure threshold must be between 0 and 1.')
      if (!Number.isFinite(noQuorumTimeoutS) || noQuorumTimeoutS < 60) throw new Error('No-quorum timeout must be >= 60.')
      if (!Number.isFinite(stageTimeoutS) || stageTimeoutS < 60) throw new Error('Stage timeout must be >= 60.')
      if (!Number.isFinite(deferRateThreshold) || deferRateThreshold < 0 || deferRateThreshold > 1) throw new Error('Defer threshold must be between 0 and 1.')
      if (!Number.isFinite(healthTimeoutS) || healthTimeoutS < 10) throw new Error('Health timeout must be >= 10.')
      if (!Number.isFinite(commandTtlS) || commandTtlS < 60) throw new Error('Command TTL must be >= 60.')
      return api.admin.createDeployment(adminCred, {
        manifest_id: manifestId,
        target_selector: targetSelector,
        rollout_stages_pct: rolloutStages,
        failure_rate_threshold: failureRateThreshold,
        no_quorum_timeout_s: noQuorumTimeoutS,
        stage_timeout_s: stageTimeoutS,
        defer_rate_threshold: deferRateThreshold,
        health_timeout_s: healthTimeoutS,
        command_ttl_s: commandTtlS,
        power_guard_required: deploymentPowerGuardRequired,
        rollback_to_tag: deploymentRollbackToTag.trim() || null,
      })
    },
    onSuccess: (deployment) => {
      setDeploymentLookupId(deployment.id)
      qc.invalidateQueries({ queryKey: ['admin', 'deployments'] })
      qc.invalidateQueries({ queryKey: ['admin', 'deploymentDetail', deployment.id] })
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
      qc.invalidateQueries({ queryKey: ['admin', 'deployments'] })
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

  const manifestCols = React.useMemo<ColumnDef<ReleaseManifestOut>[]>(() => {
    return [
      { header: 'Tag', accessorKey: 'git_tag', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Type', accessorKey: 'update_type' },
      { header: 'Status', accessorKey: 'status', cell: (i) => <Badge variant={statusVariant(String(i.getValue()))}>{String(i.getValue())}</Badge> },
      { header: 'Created', accessorKey: 'created_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as string)}</span> },
    ]
  }, [])

  const deploymentCols = React.useMemo<ColumnDef<DeploymentOut>[]>(() => {
    return [
      { header: 'Deployment', accessorKey: 'id', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      {
        header: 'Selector',
        cell: (i) => {
          const selector = i.row.original.target_selector ?? {}
          const mode = String(selector.mode ?? 'all')
          const channel = selector.channel ? `:${String(selector.channel)}` : ''
          return <span className="font-mono text-xs">{mode}{channel}</span>
        },
      },
      { header: 'Status', accessorKey: 'status', cell: (i) => <Badge variant={statusVariant(String(i.getValue()))}>{String(i.getValue())}</Badge> },
      { header: 'Healthy', cell: (i) => <span className="font-mono text-xs">{i.row.original.healthy_targets}/{i.row.original.total_targets}</span> },
      { header: 'Updated', accessorKey: 'updated_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as string)}</span> },
    ]
  }, [])

  const targetCols = React.useMemo<ColumnDef<DeploymentTargetOut>[]>(() => {
    return [
      {
        header: 'Device',
        cell: (i) => (
          <Link to="/devices/$deviceId" params={{ deviceId: i.row.original.device_id }} className="font-mono text-xs underline">
            {i.row.original.device_id}
          </Link>
        ),
      },
      { header: 'Stage', accessorKey: 'stage_assigned', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Status', accessorKey: 'status', cell: (i) => <Badge variant={statusVariant(String(i.getValue()))}>{String(i.getValue())}</Badge> },
      { header: 'Last report', accessorKey: 'last_report_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime((i.getValue() as string | null) ?? null)}</span> },
      { header: 'Failure', accessorKey: 'failure_reason', cell: (i) => <span className="text-muted-foreground">{String(i.getValue() ?? '—')}</span> },
    ]
  }, [])

  return (
    <Page
      title="Releases"
      description="Manifest lifecycle, rollout control, and target-level deployment inspection."
      actions={
        <div className="flex items-center gap-2">
          {selectedManifest ? <Badge variant="secondary">{selectedManifest.git_tag}</Badge> : null}
          {deploymentLookupId ? <Badge variant="outline">{deploymentLookupId}</Badge> : null}
          <Link
            to="/admin"
            search={{
              tab: '',
              deviceId: '',
              batchId: '',
              accessDeviceId: '',
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
            }}
            className="underline text-sm"
          >
            publish in admin
          </Link>
        </div>
      }
    >
      {!adminEnabled ? (
        <Callout title="Admin routes disabled" tone="warning">
          This page requires admin routes and OTA routes to be enabled on the API service.
        </Callout>
      ) : null}
      {adminEnabled && !adminAccess ? (
        <Callout title="Admin access required" tone="warning">
          {adminAccessHint(null, adminAuthMode) ?? 'Provide valid admin credentials to manage releases.'}
        </Callout>
      ) : null}
      {adminEnabled && adminAccess && !otaUpdatesEnabled ? (
        <Callout title="OTA routes disabled" tone="warning">
          Enable <span className="font-mono">ENABLE_OTA_UPDATES=1</span> on the API service to use release and deployment controls.
        </Callout>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-2">
        <Card id="releases-publish-manifest">
          <CardHeader>
            <CardTitle>Publish manifest</CardTitle>
            <CardDescription>Create an artifact-aware release manifest directly from the release workspace.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-2">
                <Label>Git tag</Label>
                <Input value={manifestGitTag} onChange={(e) => setManifestGitTag(e.target.value)} placeholder="v1.4.0" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
              <div className="space-y-2">
                <Label>Commit SHA</Label>
                <Input value={manifestCommitSha} onChange={(e) => setManifestCommitSha(e.target.value)} placeholder="abc123..." disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
              <div className="space-y-2">
                <Label>Update type</Label>
                <select className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={manifestUpdateType} onChange={(e) => setManifestUpdateType(e.target.value as 'application_bundle' | 'asset_bundle' | 'system_image')} disabled={inputsDisabled || !otaUpdatesEnabled}>
                  <option value="application_bundle">application_bundle</option>
                  <option value="asset_bundle">asset_bundle</option>
                  <option value="system_image">system_image</option>
                </select>
              </div>
              <div className="space-y-2">
                <Label>Status</Label>
                <Input value={manifestStatus} onChange={(e) => setManifestStatus(e.target.value)} placeholder="active" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
              <div className="space-y-2">
                <Label>Artifact size</Label>
                <Input value={manifestArtifactSize} onChange={(e) => setManifestArtifactSize(e.target.value)} placeholder="1024" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
              <div className="space-y-2">
                <Label>Signature key ID</Label>
                <Input value={manifestSignatureKeyId} onChange={(e) => setManifestSignatureKeyId(e.target.value)} placeholder="ops-key-1" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Artifact URI</Label>
              <Input value={manifestArtifactUri} onChange={(e) => setManifestArtifactUri(e.target.value)} placeholder="https://example.com/releases/v1.4.0.tar" disabled={inputsDisabled || !otaUpdatesEnabled} />
            </div>
            <div className="space-y-2">
              <Label>Artifact SHA256</Label>
              <Input value={manifestArtifactSha256} onChange={(e) => setManifestArtifactSha256(e.target.value)} placeholder="64-char sha256" disabled={inputsDisabled || !otaUpdatesEnabled} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-2">
                <Label>Artifact signature scheme</Label>
                <select className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={manifestArtifactSignatureScheme} onChange={(e) => setManifestArtifactSignatureScheme(e.target.value as 'none' | 'openssl_rsa_sha256')} disabled={inputsDisabled || !otaUpdatesEnabled}>
                  <option value="none">none</option>
                  <option value="openssl_rsa_sha256">openssl_rsa_sha256</option>
                </select>
              </div>
              <div className="space-y-2">
                <Label>Artifact signature</Label>
                <Input value={manifestArtifactSignature} onChange={(e) => setManifestArtifactSignature(e.target.value)} placeholder="base64 artifact signature" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Signature</Label>
              <Input value={manifestSignature} onChange={(e) => setManifestSignature(e.target.value)} placeholder="base64-signature" disabled={inputsDisabled || !otaUpdatesEnabled} />
            </div>
            <div className="space-y-2">
              <Label>Constraints JSON</Label>
              <textarea className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono" value={manifestConstraints} onChange={(e) => setManifestConstraints(e.target.value)} disabled={inputsDisabled || !otaUpdatesEnabled} />
            </div>
            <div className="space-y-2">
              <Label>Compatibility JSON</Label>
              <textarea className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono" value={manifestCompatibility} onChange={(e) => setManifestCompatibility(e.target.value)} disabled={inputsDisabled || !otaUpdatesEnabled} />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" onClick={() => createManifestMutation.mutate()} disabled={inputsDisabled || !otaUpdatesEnabled || createManifestMutation.isPending}>
                {createManifestMutation.isPending ? 'Creating manifest…' : 'Create manifest'}
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card id="releases-launch-deployment">
          <CardHeader>
            <CardTitle>Launch deployment</CardTitle>
            <CardDescription>Create a staged rollout from the selected or pasted manifest ID.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-2 lg:col-span-2">
                <Label>Manifest ID</Label>
                <Input value={deploymentManifestId} onChange={(e) => setDeploymentManifestId(e.target.value)} placeholder="manifest UUID" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
              <div className="space-y-2">
                <Label>Selector mode</Label>
                <select className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={deploymentSelectorMode} onChange={(e) => setDeploymentSelectorMode(e.target.value as 'all' | 'cohort' | 'labels' | 'explicit_ids' | 'channel')} disabled={inputsDisabled || !otaUpdatesEnabled}>
                  <option value="all">all</option>
                  <option value="cohort">cohort</option>
                  <option value="channel">channel</option>
                  <option value="labels">labels</option>
                  <option value="explicit_ids">explicit_ids</option>
                </select>
              </div>
              {deploymentSelectorMode === 'cohort' ? (
                <div className="space-y-2">
                  <Label>Cohort</Label>
                  <Input value={deploymentSelectorCohort} onChange={(e) => setDeploymentSelectorCohort(e.target.value)} placeholder="pilot-west" disabled={inputsDisabled || !otaUpdatesEnabled} />
                </div>
              ) : null}
              {deploymentSelectorMode === 'channel' ? (
                <div className="space-y-2">
                  <Label>Channel</Label>
                  <Input value={deploymentSelectorChannel} onChange={(e) => setDeploymentSelectorChannel(e.target.value)} placeholder="stable" disabled={inputsDisabled || !otaUpdatesEnabled} />
                </div>
              ) : null}
              {deploymentSelectorMode === 'labels' ? (
                <div className="space-y-2 lg:col-span-2">
                  <Label>Labels JSON</Label>
                  <textarea className="min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono" value={deploymentSelectorLabels} onChange={(e) => setDeploymentSelectorLabels(e.target.value)} disabled={inputsDisabled || !otaUpdatesEnabled} />
                </div>
              ) : null}
              {deploymentSelectorMode === 'explicit_ids' ? (
                <div className="space-y-2 lg:col-span-2">
                  <Label>Device IDs (comma-separated)</Label>
                  <Input value={deploymentSelectorIds} onChange={(e) => setDeploymentSelectorIds(e.target.value)} placeholder="well-001, well-002" disabled={inputsDisabled || !otaUpdatesEnabled} />
                </div>
              ) : null}
              <div className="space-y-2">
                <Label>Rollout stages</Label>
                <Input value={deploymentRolloutStages} onChange={(e) => setDeploymentRolloutStages(e.target.value)} placeholder="1,10,50,100" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
              <div className="space-y-2">
                <Label>Failure threshold</Label>
                <Input value={deploymentFailureRateThreshold} onChange={(e) => setDeploymentFailureRateThreshold(e.target.value)} placeholder="0.2" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
              <div className="space-y-2">
                <Label>No-quorum timeout (s)</Label>
                <Input value={deploymentNoQuorumTimeoutS} onChange={(e) => setDeploymentNoQuorumTimeoutS(e.target.value)} placeholder="1800" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
              <div className="space-y-2">
                <Label>Stage timeout (s)</Label>
                <Input value={deploymentStageTimeoutS} onChange={(e) => setDeploymentStageTimeoutS(e.target.value)} placeholder="1800" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
              <div className="space-y-2">
                <Label>Defer threshold</Label>
                <Input value={deploymentDeferRateThreshold} onChange={(e) => setDeploymentDeferRateThreshold(e.target.value)} placeholder="0.5" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
              <div className="space-y-2">
                <Label>Health timeout (s)</Label>
                <Input value={deploymentHealthTimeoutS} onChange={(e) => setDeploymentHealthTimeoutS(e.target.value)} placeholder="300" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
              <div className="space-y-2">
                <Label>Command TTL (s)</Label>
                <Input value={deploymentCommandTtlS} onChange={(e) => setDeploymentCommandTtlS(e.target.value)} placeholder="15552000" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
              <div className="space-y-2">
                <Label>Rollback tag (optional)</Label>
                <Input value={deploymentRollbackToTag} onChange={(e) => setDeploymentRollbackToTag(e.target.value)} placeholder="v1.3.9" disabled={inputsDisabled || !otaUpdatesEnabled} />
              </div>
              <div className="space-y-2">
                <Label>Power guard required</Label>
                <div className="flex items-center gap-2">
                  <input type="checkbox" checked={deploymentPowerGuardRequired} onChange={(e) => setDeploymentPowerGuardRequired(e.target.checked)} disabled={inputsDisabled || !otaUpdatesEnabled} />
                  <span className="text-sm text-muted-foreground">defer when power is unstable</span>
                </div>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={() => createDeploymentMutation.mutate()} disabled={inputsDisabled || !otaUpdatesEnabled || createDeploymentMutation.isPending}>
                {createDeploymentMutation.isPending ? 'Creating deployment…' : 'Create deployment'}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.1fr_1.3fr]">
        <Card id="releases-manifests">
          <CardHeader>
            <CardTitle>Release manifests</CardTitle>
            <CardDescription>Filter, promote, draft, or retire manifests without leaving the release workspace.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Input
                value={manifestFilterStatus}
                onChange={(e) => setManifestFilterStatus(e.target.value)}
                placeholder="status filter"
                disabled={inputsDisabled || !otaUpdatesEnabled}
              />
              <Button variant="outline" onClick={() => setManifestFilterStatus('')} disabled={inputsDisabled || !otaUpdatesEnabled}>
                Clear
              </Button>
            </div>
            {manifestsQ.isError ? <div className="text-sm text-destructive">Error: {(manifestsQ.error as Error).message}</div> : null}
            <DataTable<ReleaseManifestOut>
              data={manifestsQ.data ?? []}
              columns={manifestCols}
              onRowClick={(row) => setSelectedManifestId(row.id)}
              emptyState="No manifests matched the current filter."
            />
            {selectedManifest ? (
              <div className="space-y-3 rounded-md border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">{selectedManifest.git_tag}</Badge>
                  <Badge variant={statusVariant(selectedManifest.status)}>{selectedManifest.status}</Badge>
                  <span className="font-mono text-xs text-muted-foreground">{selectedManifest.id}</span>
                </div>
                <div className="text-xs text-muted-foreground">
                  {selectedManifest.update_type} · created {fmtDateTime(selectedManifest.created_at)}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => updateManifestStatusMutation.mutate({ manifestId: selectedManifest.id, status: 'draft' })}
                    disabled={updateManifestStatusMutation.isPending || selectedManifest.status === 'draft'}
                  >
                    Draft
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => updateManifestStatusMutation.mutate({ manifestId: selectedManifest.id, status: 'active' })}
                    disabled={updateManifestStatusMutation.isPending || selectedManifest.status === 'active'}
                  >
                    Promote
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => updateManifestStatusMutation.mutate({ manifestId: selectedManifest.id, status: 'retired' })}
                    disabled={updateManifestStatusMutation.isPending || selectedManifest.status === 'retired'}
                  >
                    Retire
                  </Button>
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card id="releases-deployments">
          <CardHeader>
            <CardTitle>Deployments</CardTitle>
            <CardDescription>Filter and inspect recent rollouts without needing deployment IDs from elsewhere.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Input
                value={recentDeploymentStatus}
                onChange={(e) => setRecentDeploymentStatus(e.target.value)}
                placeholder="status filter"
                disabled={inputsDisabled || !otaUpdatesEnabled}
              />
              <Input
                value={recentDeploymentChannel}
                onChange={(e) => setRecentDeploymentChannel(e.target.value)}
                placeholder="channel filter"
                disabled={inputsDisabled || !otaUpdatesEnabled}
              />
              <Button
                variant="outline"
                onClick={() => {
                  setRecentDeploymentStatus('')
                  setRecentDeploymentChannel('')
                }}
                disabled={inputsDisabled || !otaUpdatesEnabled}
              >
                Clear
              </Button>
            </div>
            {deploymentsQ.isError ? <div className="text-sm text-destructive">Error: {(deploymentsQ.error as Error).message}</div> : null}
            <DataTable<DeploymentOut>
              data={deploymentsQ.data ?? []}
              columns={deploymentCols}
              onRowClick={(row) => setDeploymentLookupId(row.id)}
              emptyState="No deployments matched the current filters."
            />
          </CardContent>
        </Card>
      </div>

      {deploymentDetailQ.data ? (
        <Card id="releases-deployment-inspector">
          <CardHeader>
            <CardTitle>Deployment inspector</CardTitle>
            <CardDescription>Target-level rollout state, intervention controls, and event history.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={statusVariant(deploymentDetailQ.data.status)}>{deploymentDetailQ.data.status}</Badge>
              <span className="font-mono text-xs">stage {deploymentDetailQ.data.stage}</span>
              <span className="font-mono text-xs">targets {deploymentDetailQ.data.total_targets}</span>
              <span className="font-mono text-xs">healthy {deploymentDetailQ.data.healthy_targets}</span>
              <span className="font-mono text-xs">failed {deploymentDetailQ.data.failed_targets}</span>
              <span className="font-mono text-xs">deferred {deploymentDetailQ.data.deferred_targets}</span>
            </div>
            <div className="text-xs text-muted-foreground">
              Deployment <span className="font-mono">{deploymentDetailQ.data.id}</span>
              {' · '}manifest <span className="font-mono">{deploymentDetailQ.data.manifest.git_tag}</span>
              {' · '}updated <span className="font-mono">{fmtDateTime(deploymentDetailQ.data.updated_at)}</span>
            </div>
            {deploymentDetailQ.data.halt_reason ? (
              <div className="text-sm text-destructive">Halt reason: {deploymentDetailQ.data.halt_reason}</div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => deploymentActionMutation.mutate('pause')}
                disabled={deploymentActionMutation.isPending || deploymentDetailQ.data.status !== 'active'}
              >
                Pause
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => deploymentActionMutation.mutate('resume')}
                disabled={deploymentActionMutation.isPending || deploymentDetailQ.data.status !== 'paused'}
              >
                Resume
              </Button>
              <Input
                value={deploymentAbortReason}
                onChange={(e) => setDeploymentAbortReason(e.target.value)}
                placeholder="abort reason"
                disabled={deploymentActionMutation.isPending}
              />
              <Button
                type="button"
                variant="destructive"
                onClick={() => deploymentActionMutation.mutate('abort')}
                disabled={deploymentActionMutation.isPending || deploymentDetailQ.data.status === 'aborted' || deploymentDetailQ.data.status === 'completed'}
              >
                Abort
              </Button>
            </div>

            <div className="space-y-2 rounded-md border p-3">
              <div className="text-sm font-medium">Deployment targets</div>
              <div className="flex flex-wrap gap-2">
                <Input
                  value={deploymentTargetStatusFilter}
                  onChange={(e) => setDeploymentTargetStatusFilter(e.target.value)}
                  placeholder="status filter"
                  disabled={inputsDisabled || !otaUpdatesEnabled}
                />
                <Input
                  value={deploymentTargetSearch}
                  onChange={(e) => setDeploymentTargetSearch(e.target.value)}
                  placeholder="search device or failure"
                  disabled={inputsDisabled || !otaUpdatesEnabled}
                />
                <select
                  className="h-10 rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={deploymentTargetLimit}
                  onChange={(e) => setDeploymentTargetLimit(e.target.value)}
                  disabled={inputsDisabled || !otaUpdatesEnabled}
                >
                  <option value="50">50 / page</option>
                  <option value="100">100 / page</option>
                  <option value="200">200 / page</option>
                </select>
                <Button
                  variant="outline"
                  onClick={() => {
                    setDeploymentTargetStatusFilter('')
                    setDeploymentTargetSearch('')
                  }}
                  disabled={inputsDisabled || !otaUpdatesEnabled}
                >
                  Clear
                </Button>
              </div>
              {deploymentTargetsQ.isError ? <div className="text-sm text-destructive">Error: {(deploymentTargetsQ.error as Error).message}</div> : null}
              {deploymentTargetsQ.data ? (
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>
                    Showing {deploymentTargetPage.start}-{deploymentTargetPage.end} of {deploymentTargetPage.total} matching targets.
                  </span>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setDeploymentTargetOffset((current) => Math.max(0, current - deploymentTargetPage.limit))}
                      disabled={deploymentTargetPage.offset <= 0}
                    >
                      Previous page
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setDeploymentTargetOffset((current) => current + deploymentTargetPage.limit)}
                      disabled={deploymentTargetPage.offset + deploymentTargetPage.limit >= deploymentTargetPage.total}
                    >
                      Next page
                    </Button>
                  </div>
                </div>
              ) : null}
              <DataTable<DeploymentTargetOut>
                data={deploymentTargetsQ.data?.items ?? []}
                columns={targetCols}
                emptyState="No deployment targets matched the current filters."
              />
            </div>

            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Recent deployment events</summary>
              <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words">
                {JSON.stringify((deploymentDetailQ.data as DeploymentDetailOut).events.slice(0, 30), null, 2)}
              </pre>
            </details>
          </CardContent>
        </Card>
      ) : null}
    </Page>
  )
}
