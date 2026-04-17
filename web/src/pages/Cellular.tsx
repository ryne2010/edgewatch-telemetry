import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link } from '@tanstack/react-router'
import { api, type DeviceSummaryOut } from '../api'
import { useAppSettings } from '../app/settings'
import { useAdminAccess } from '../hooks/useAdminAccess'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Input, Label, Page, useToast } from '../ui-kit'
import { adminAccessHint } from '../utils/adminAuth'
import { fmtDateTime, fmtNumber } from '../utils/format'

const CELLULAR_METRICS = [
  'signal_rssi_dbm',
  'cellular_rsrp_dbm',
  'cellular_rsrq_db',
  'cellular_sinr_db',
  'cellular_registration_state',
  'cellular_bytes_sent_today',
  'cellular_bytes_received_today',
  'link_ok',
  'link_last_ok_at',
  'cost_cap_active',
  'bytes_sent_today',
] as const

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function formatBytes(value: number | null): string {
  if (value == null) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${fmtNumber(value / 1024, { digits: 1 })} KB`
  if (value < 1024 * 1024 * 1024) return `${fmtNumber(value / (1024 * 1024), { digits: 1 })} MB`
  return `${fmtNumber(value / (1024 * 1024 * 1024), { digits: 2 })} GB`
}

function signalVariant(rssi: number | null): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (rssi == null) return 'secondary'
  if (rssi < -105) return 'destructive'
  if (rssi < -95) return 'warning'
  return 'success'
}

function parsePositiveWholeNumber(label: string, value: string): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || !Number.isInteger(parsed) || parsed < 1) {
    throw new Error(`${label} must be a whole number greater than 0.`)
  }
  return parsed
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function setYamlNumericValue(yamlText: string, key: string, value: number): string {
  const pattern = new RegExp(`^(\\s*${escapeRegExp(key)}\\s*:\\s*)([^#\\n]*?)(\\s*(#.*)?)$`, 'm')
  if (!pattern.test(yamlText)) throw new Error(`Could not find '${key}' in edge policy YAML`)
  return yamlText.replace(pattern, (_m, prefix: string, _current: string, suffix: string | undefined) => {
    return `${prefix}${String(Math.trunc(value))}${suffix ?? ''}`
  })
}

export function CellularPage() {
  const { adminKey } = useAppSettings()
  const { toast } = useToast()
  const qc = useQueryClient()
  const [filterText, setFilterText] = React.useState('')
  const [focus, setFocus] = React.useState<'all' | 'weak_signal' | 'cost_cap' | 'registration_issue' | 'link_down'>('all')
  const [maxBytesPerDayInput, setMaxBytesPerDayInput] = React.useState('25000000')
  const [maxMediaUploadsPerDayInput, setMaxMediaUploadsPerDayInput] = React.useState('20')
  const [maxSnapshotsPerDayInput, setMaxSnapshotsPerDayInput] = React.useState('50')

  const healthQ = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })

  const adminEnabled = Boolean(healthQ.data?.features?.admin?.enabled)
  const adminAuthMode = String(healthQ.data?.features?.admin?.auth_mode ?? 'key').toLowerCase()
  const { adminAccess, adminCred } = useAdminAccess({
    adminEnabled,
    adminAuthMode,
    adminKey,
  })

  const devicesQ = useQuery({
    queryKey: ['devicesSummary', 'cellularPage'],
    queryFn: () => api.devicesSummary({ metrics: [...CELLULAR_METRICS] }),
    refetchInterval: 15_000,
  })

  const policyQ = useQuery({
    queryKey: ['edgePolicyContract'],
    queryFn: api.edgePolicyContract,
    enabled: healthQ.isSuccess,
    staleTime: 30_000,
  })

  const policySourceQ = useQuery({
    queryKey: ['admin', 'edgePolicyContractSource', adminCred],
    queryFn: () => api.admin.edgePolicyContractSource(adminCred),
    enabled: healthQ.isSuccess && adminAccess,
    refetchOnWindowFocus: false,
  })

  React.useEffect(() => {
    if (!policyQ.data) return
    setMaxBytesPerDayInput(String(policyQ.data.cost_caps.max_bytes_per_day))
    setMaxMediaUploadsPerDayInput(String(policyQ.data.cost_caps.max_media_uploads_per_day))
    setMaxSnapshotsPerDayInput(String(policyQ.data.cost_caps.max_snapshots_per_day))
  }, [policyQ.data?.policy_sha256])

  const policyDirty = React.useMemo(() => {
    if (!policyQ.data) return false
    return (
      maxBytesPerDayInput !== String(policyQ.data.cost_caps.max_bytes_per_day) ||
      maxMediaUploadsPerDayInput !== String(policyQ.data.cost_caps.max_media_uploads_per_day) ||
      maxSnapshotsPerDayInput !== String(policyQ.data.cost_caps.max_snapshots_per_day)
    )
  }, [maxBytesPerDayInput, maxMediaUploadsPerDayInput, maxSnapshotsPerDayInput, policyQ.data])

  const saveCapsMutation = useMutation({
    mutationFn: async () => {
      if (!adminAccess) throw new Error('Admin access required.')
      const yamlText = policySourceQ.data?.yaml_text
      if (!yamlText?.trim()) throw new Error('Policy YAML source is not loaded.')
      const maxBytesPerDay = parsePositiveWholeNumber('Max bytes per day', maxBytesPerDayInput)
      const maxMediaUploadsPerDay = parsePositiveWholeNumber('Max media uploads per day', maxMediaUploadsPerDayInput)
      const maxSnapshotsPerDay = parsePositiveWholeNumber('Max snapshots per day', maxSnapshotsPerDayInput)
      let nextYaml = yamlText
      nextYaml = setYamlNumericValue(nextYaml, 'max_bytes_per_day', maxBytesPerDay)
      nextYaml = setYamlNumericValue(nextYaml, 'max_media_uploads_per_day', maxMediaUploadsPerDay)
      nextYaml = setYamlNumericValue(nextYaml, 'max_snapshots_per_day', maxSnapshotsPerDay)
      return api.admin.updateEdgePolicyContract(adminCred, { yaml_text: nextYaml })
    },
    onSuccess: () => {
      toast({ title: 'Cellular cost caps saved', variant: 'success' })
      qc.invalidateQueries({ queryKey: ['edgePolicyContract'] })
      qc.invalidateQueries({ queryKey: ['admin', 'edgePolicyContractSource'] })
      qc.invalidateQueries({ queryKey: ['devicesSummary'] })
    },
    onError: (error) => {
      toast({
        title: 'Unable to save cellular cost caps',
        description: adminAccessHint(error, adminAuthMode) ?? (error as Error).message,
        variant: 'error',
      })
    },
  })

  const applyCostPreset = React.useCallback((preset: 'conservative' | 'balanced' | 'aggressive') => {
    if (preset === 'conservative') {
      setMaxBytesPerDayInput('10000000')
      setMaxMediaUploadsPerDayInput('8')
      setMaxSnapshotsPerDayInput('20')
      return
    }
    if (preset === 'aggressive') {
      setMaxBytesPerDayInput('100000000')
      setMaxMediaUploadsPerDayInput('100')
      setMaxSnapshotsPerDayInput('200')
      return
    }
    setMaxBytesPerDayInput('25000000')
    setMaxMediaUploadsPerDayInput('20')
    setMaxSnapshotsPerDayInput('50')
  }, [])

  const rows = devicesQ.data ?? []
  const filtered = React.useMemo(() => {
    const q = filterText.trim().toLowerCase()
    return rows.filter((row) => {
      const registration = String(row.metrics?.cellular_registration_state ?? '').toLowerCase()
      const rssi = asNumber(row.metrics?.signal_rssi_dbm)
      const linkOk = row.metrics?.link_ok === true
      const capActive = row.metrics?.cost_cap_active === true
      const registrationIssue = registration !== '' && registration !== 'home' && registration !== 'roaming'
      if (focus === 'weak_signal' && !(rssi != null && rssi < -95)) return false
      if (focus === 'cost_cap' && !capActive) return false
      if (focus === 'registration_issue' && !registrationIssue) return false
      if (focus === 'link_down' && linkOk) return false
      if (!q) return true
      return (
        row.device_id.toLowerCase().includes(q) ||
        row.display_name.toLowerCase().includes(q) ||
        registration.includes(q)
      )
    })
  }, [rows, filterText, focus])

  const summary = React.useMemo(() => {
    const total = rows.length
    const weakSignal = rows.filter((row) => {
      const rssi = asNumber(row.metrics?.signal_rssi_dbm)
      return rssi != null && rssi < -95
    }).length
    const capActive = rows.filter((row) => row.metrics?.cost_cap_active === true).length
    const linkDown = rows.filter((row) => row.metrics?.link_ok !== true).length
    const registrationIssue = rows.filter((row) => {
      const registration = String(row.metrics?.cellular_registration_state ?? '').toLowerCase()
      return registration !== '' && registration !== 'home' && registration !== 'roaming'
    }).length
    const connected = rows.filter((row) => {
      const registration = String(row.metrics?.cellular_registration_state ?? '').toLowerCase()
      return registration === 'home' || registration === 'roaming'
    }).length
    const totalBytes = rows.reduce((sum, row) => {
      const sent = asNumber(row.metrics?.cellular_bytes_sent_today) ?? 0
      const recv = asNumber(row.metrics?.cellular_bytes_received_today) ?? 0
      return sum + sent + recv
    }, 0)
    return { total, weakSignal, capActive, connected, totalBytes, linkDown, registrationIssue }
  }, [rows])

  const costCapShare = summary.total ? Math.round((summary.capActive / summary.total) * 100) : 0

  const cols = React.useMemo<ColumnDef<DeviceSummaryOut>[]>(() => {
    return [
      {
        header: 'Device',
        accessorKey: 'device_id',
        cell: (i) => (
          <Link to="/devices/$deviceId" params={{ deviceId: String(i.getValue()) }} className="font-mono text-xs underline">
            {String(i.getValue())}
          </Link>
        ),
      },
      { header: 'Name', accessorKey: 'display_name' },
      {
        header: 'Registration',
        cell: (i) => <Badge variant="secondary">{String(i.row.original.metrics?.cellular_registration_state ?? '—')}</Badge>,
      },
      {
        header: 'RSSI',
        cell: (i) => {
          const rssi = asNumber(i.row.original.metrics?.signal_rssi_dbm)
          return <Badge variant={signalVariant(rssi)}>{rssi == null ? '—' : `${fmtNumber(rssi, { digits: 0 })} dBm`}</Badge>
        },
      },
      {
        header: 'SINR',
        cell: (i) => {
          const sinr = asNumber(i.row.original.metrics?.cellular_sinr_db)
          return <span className="font-mono text-xs">{sinr == null ? '—' : `${fmtNumber(sinr, { digits: 1 })} dB`}</span>
        },
      },
      {
        header: 'RSRP',
        cell: (i) => {
          const rsrp = asNumber(i.row.original.metrics?.cellular_rsrp_dbm)
          return <span className="font-mono text-xs">{rsrp == null ? '—' : `${fmtNumber(rsrp, { digits: 0 })} dBm`}</span>
        },
      },
      {
        header: 'RSRQ',
        cell: (i) => {
          const rsrq = asNumber(i.row.original.metrics?.cellular_rsrq_db)
          return <span className="font-mono text-xs">{rsrq == null ? '—' : `${fmtNumber(rsrq, { digits: 1 })} dB`}</span>
        },
      },
      {
        header: 'Link',
        cell: (i) =>
          i.row.original.metrics?.link_ok === true ? <Badge variant="success">ok</Badge> : <Badge variant="warning">check</Badge>,
      },
      {
        header: 'Sent',
        cell: (i) => {
          const sent = asNumber(i.row.original.metrics?.cellular_bytes_sent_today)
          return <span className="font-mono text-xs">{formatBytes(sent)}</span>
        },
      },
      {
        header: 'Received',
        cell: (i) => {
          const recv = asNumber(i.row.original.metrics?.cellular_bytes_received_today)
          return <span className="font-mono text-xs">{formatBytes(recv)}</span>
        },
      },
      {
        header: 'Bytes today',
        cell: (i) => {
          const sent = asNumber(i.row.original.metrics?.cellular_bytes_sent_today)
          const recv = asNumber(i.row.original.metrics?.cellular_bytes_received_today)
          const total = (sent ?? 0) + (recv ?? 0)
          return <span className="font-mono text-xs">{formatBytes(total || null)}</span>
        },
      },
      {
        header: 'Cost cap',
        cell: (i) =>
          i.row.original.metrics?.cost_cap_active === true ? <Badge variant="destructive">active</Badge> : <Badge variant="secondary">clear</Badge>,
      },
      {
        header: 'Last link ok',
        cell: (i) => {
          const value = i.row.original.metrics?.link_last_ok_at
          return <span className="text-muted-foreground">{typeof value === 'string' ? fmtDateTime(value) : '—'}</span>
        },
      },
    ]
  }, [])

  return (
    <Page
      title="Cellular"
      description="Fleet-wide cellular health, registration, and daily usage posture."
      actions={
        <div className="flex items-center gap-2">
          <Badge variant="outline">devices: {summary.total}</Badge>
          <Badge variant="secondary">connected: {summary.connected}</Badge>
          {focus !== 'all' ? <Badge variant="warning">focus: {focus}</Badge> : null}
        </div>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader><CardTitle>Connected</CardTitle><CardDescription>Home or roaming registration</CardDescription></CardHeader>
          <CardContent><div className="text-3xl font-semibold tracking-tight">{summary.connected}</div></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Weak signal</CardTitle><CardDescription>RSSI below -95 dBm</CardDescription></CardHeader>
          <CardContent><div className="text-3xl font-semibold tracking-tight">{summary.weakSignal}</div></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Cost cap active</CardTitle><CardDescription>Upload/media budget constrained</CardDescription></CardHeader>
          <CardContent><div className="text-3xl font-semibold tracking-tight">{summary.capActive}</div></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Fleet bytes today</CardTitle><CardDescription>Cellular sent + received</CardDescription></CardHeader>
          <CardContent><div className="text-3xl font-semibold tracking-tight">{formatBytes(summary.totalBytes)}</div></CardContent>
        </Card>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader><CardTitle>Link down</CardTitle><CardDescription>Watchdog not currently healthy</CardDescription></CardHeader>
          <CardContent><div className="text-3xl font-semibold tracking-tight">{summary.linkDown}</div></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Registration issue</CardTitle><CardDescription>Denied, searching, or non-home/roaming</CardDescription></CardHeader>
          <CardContent><div className="text-3xl font-semibold tracking-tight">{summary.registrationIssue}</div></CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Cost cap policy</CardTitle>
          <CardDescription>Current fleet budget posture plus quick-write controls for daily bytes, snapshots, and media uploads.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border bg-muted/20 p-4">
              <div className="text-sm text-muted-foreground">Daily bytes cap</div>
              <div className="mt-1 text-2xl font-semibold tracking-tight">
                {formatBytes(policyQ.data?.cost_caps.max_bytes_per_day ?? null)}
              </div>
            </div>
            <div className="rounded-lg border bg-muted/20 p-4">
              <div className="text-sm text-muted-foreground">Daily media uploads cap</div>
              <div className="mt-1 text-2xl font-semibold tracking-tight">
                {fmtNumber(policyQ.data?.cost_caps.max_media_uploads_per_day ?? 0, { digits: 0 })}
              </div>
            </div>
            <div className="rounded-lg border bg-muted/20 p-4">
              <div className="text-sm text-muted-foreground">Daily snapshots cap</div>
              <div className="mt-1 text-2xl font-semibold tracking-tight">
                {fmtNumber(policyQ.data?.cost_caps.max_snapshots_per_day ?? 0, { digits: 0 })}
              </div>
            </div>
            <div className="rounded-lg border bg-muted/20 p-4">
              <div className="text-sm text-muted-foreground">Devices currently capped</div>
              <div className="mt-1 text-2xl font-semibold tracking-tight">
                {summary.capActive} <span className="text-sm text-muted-foreground">({costCapShare}% of fleet)</span>
              </div>
            </div>
          </div>

          {adminAccess ? (
            <div className="grid gap-4 rounded-lg border p-4">
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => applyCostPreset('conservative')}>Conservative preset</Button>
                <Button variant="outline" onClick={() => applyCostPreset('balanced')}>Balanced preset</Button>
                <Button variant="outline" onClick={() => applyCostPreset('aggressive')}>Aggressive preset</Button>
              </div>
              <div className="grid gap-4 md:grid-cols-3">
                <div className="space-y-1">
                  <Label>Max bytes per day</Label>
                  <Input
                    type="number"
                    value={maxBytesPerDayInput}
                    onChange={(e) => setMaxBytesPerDayInput(e.target.value)}
                    disabled={saveCapsMutation.isPending}
                  />
                </div>
                <div className="space-y-1">
                  <Label>Max media uploads per day</Label>
                  <Input
                    type="number"
                    value={maxMediaUploadsPerDayInput}
                    onChange={(e) => setMaxMediaUploadsPerDayInput(e.target.value)}
                    disabled={saveCapsMutation.isPending}
                  />
                </div>
                <div className="space-y-1">
                  <Label>Max snapshots per day</Label>
                  <Input
                    type="number"
                    value={maxSnapshotsPerDayInput}
                    onChange={(e) => setMaxSnapshotsPerDayInput(e.target.value)}
                    disabled={saveCapsMutation.isPending}
                  />
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="outline" onClick={() => saveCapsMutation.mutate()} disabled={!policyDirty || saveCapsMutation.isPending}>
                  {saveCapsMutation.isPending ? 'Saving caps…' : 'Save cost-cap policy'}
                </Button>
                {!policyDirty ? <span className="text-xs text-muted-foreground">No unsaved cap changes.</span> : null}
                <span className="text-xs text-muted-foreground">
                  This updates the shared edge policy contract used by devices during policy refresh.
                </span>
              </div>
            </div>
          ) : adminEnabled ? (
            <div className="text-sm text-muted-foreground">
              {adminAccessHint(policySourceQ.error, adminAuthMode) ?? 'Admin access required to edit fleet cost-cap policy.'}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">Admin routes are disabled in this deployment.</div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Fleet cellular view</CardTitle>
          <CardDescription>Signal, registration state, link watchdog, and daily usage by device.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Input value={filterText} onChange={(e) => setFilterText(e.target.value)} placeholder="Filter by device or registration state…" />
            <Button variant="outline" onClick={() => setFilterText('')}>Clear</Button>
            <Button variant={focus === 'all' ? 'default' : 'outline'} onClick={() => setFocus('all')}>All</Button>
            <Button variant={focus === 'weak_signal' ? 'default' : 'outline'} onClick={() => setFocus('weak_signal')}>Weak signal</Button>
            <Button variant={focus === 'cost_cap' ? 'default' : 'outline'} onClick={() => setFocus('cost_cap')}>Cost cap</Button>
            <Button variant={focus === 'registration_issue' ? 'default' : 'outline'} onClick={() => setFocus('registration_issue')}>Registration issues</Button>
            <Button variant={focus === 'link_down' ? 'default' : 'outline'} onClick={() => setFocus('link_down')}>Link down</Button>
          </div>
          {devicesQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
          {devicesQ.isError ? <div className="text-sm text-destructive">Error: {(devicesQ.error as Error).message}</div> : null}
          <DataTable<DeviceSummaryOut>
            data={filtered}
            columns={cols}
            emptyState="No fleet devices matched the current cellular filter."
          />
        </CardContent>
      </Card>
    </Page>
  )
}
