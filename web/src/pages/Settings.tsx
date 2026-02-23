import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { api, type EdgePolicyContractOut, type NotificationDestinationOut } from '../api'
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
  Separator,
  Textarea,
  useToast,
} from '../ui-kit'
import { adminAccessHint } from '../utils/adminAuth'

type ImportantPolicyDraft = {
  sample_interval_s: string
  heartbeat_interval_s: string
  alert_sample_interval_s: string
  alert_report_interval_s: string
  max_points_per_batch: string

  water_pressure_low_psi: string
  water_pressure_recover_psi: string
  oil_pressure_low_psi: string
  oil_pressure_recover_psi: string
  battery_low_v: string
  battery_recover_v: string
  signal_low_rssi_dbm: string
  signal_recover_rssi_dbm: string

  max_bytes_per_day: string
  max_media_uploads_per_day: string
}

type ParsedPolicyDraft = {
  [K in keyof ImportantPolicyDraft]: number
}

type MetricRow = { key: string; type: string; unit: string; description: string }
type DeltaRow = { key: string; threshold: number }

const IMPORTANT_POLICY_KEYS: Array<keyof ImportantPolicyDraft> = [
  'sample_interval_s',
  'heartbeat_interval_s',
  'alert_sample_interval_s',
  'alert_report_interval_s',
  'max_points_per_batch',

  'water_pressure_low_psi',
  'water_pressure_recover_psi',
  'oil_pressure_low_psi',
  'oil_pressure_recover_psi',
  'battery_low_v',
  'battery_recover_v',
  'signal_low_rssi_dbm',
  'signal_recover_rssi_dbm',

  'max_bytes_per_day',
  'max_media_uploads_per_day',
]

function buildImportantPolicyDraft(policy: EdgePolicyContractOut): ImportantPolicyDraft {
  return {
    sample_interval_s: String(policy.reporting.sample_interval_s),
    heartbeat_interval_s: String(policy.reporting.heartbeat_interval_s),
    alert_sample_interval_s: String(policy.reporting.alert_sample_interval_s),
    alert_report_interval_s: String(policy.reporting.alert_report_interval_s),
    max_points_per_batch: String(policy.reporting.max_points_per_batch),

    water_pressure_low_psi: String(policy.alert_thresholds.water_pressure_low_psi),
    water_pressure_recover_psi: String(policy.alert_thresholds.water_pressure_recover_psi),
    oil_pressure_low_psi: String(policy.alert_thresholds.oil_pressure_low_psi),
    oil_pressure_recover_psi: String(policy.alert_thresholds.oil_pressure_recover_psi),
    battery_low_v: String(policy.alert_thresholds.battery_low_v),
    battery_recover_v: String(policy.alert_thresholds.battery_recover_v),
    signal_low_rssi_dbm: String(policy.alert_thresholds.signal_low_rssi_dbm),
    signal_recover_rssi_dbm: String(policy.alert_thresholds.signal_recover_rssi_dbm),

    max_bytes_per_day: String(policy.cost_caps.max_bytes_per_day),
    max_media_uploads_per_day: String(policy.cost_caps.max_media_uploads_per_day),
  }
}

function policyDraftEqual(a: ImportantPolicyDraft | null, b: ImportantPolicyDraft | null): boolean {
  if (!a || !b) return false
  return (Object.keys(a) as Array<keyof ImportantPolicyDraft>).every((k) => a[k] === b[k])
}

function parseIntField(label: string, raw: string, min: number): number {
  const n = Number(raw)
  if (!Number.isFinite(n) || !Number.isInteger(n)) throw new Error(`${label} must be a whole number`)
  if (n < min) throw new Error(`${label} must be >= ${min}`)
  return n
}

function parseNumberField(label: string, raw: string): number {
  const n = Number(raw)
  if (!Number.isFinite(n)) throw new Error(`${label} must be a number`)
  return n
}

function parseImportantPolicyDraft(draft: ImportantPolicyDraft): ParsedPolicyDraft {
  const parsed: ParsedPolicyDraft = {
    sample_interval_s: parseIntField('Sample interval', draft.sample_interval_s, 1),
    heartbeat_interval_s: parseIntField('Heartbeat interval', draft.heartbeat_interval_s, 1),
    alert_sample_interval_s: parseIntField('Alert sample interval', draft.alert_sample_interval_s, 1),
    alert_report_interval_s: parseIntField('Alert report interval', draft.alert_report_interval_s, 1),
    max_points_per_batch: parseIntField('Max points per batch', draft.max_points_per_batch, 1),

    water_pressure_low_psi: parseNumberField('Water pressure low', draft.water_pressure_low_psi),
    water_pressure_recover_psi: parseNumberField('Water pressure recover', draft.water_pressure_recover_psi),
    oil_pressure_low_psi: parseNumberField('Oil pressure low', draft.oil_pressure_low_psi),
    oil_pressure_recover_psi: parseNumberField('Oil pressure recover', draft.oil_pressure_recover_psi),
    battery_low_v: parseNumberField('Battery low', draft.battery_low_v),
    battery_recover_v: parseNumberField('Battery recover', draft.battery_recover_v),
    signal_low_rssi_dbm: parseNumberField('Signal low', draft.signal_low_rssi_dbm),
    signal_recover_rssi_dbm: parseNumberField('Signal recover', draft.signal_recover_rssi_dbm),

    max_bytes_per_day: parseIntField('Max bytes per day', draft.max_bytes_per_day, 1),
    max_media_uploads_per_day: parseIntField('Max media uploads per day', draft.max_media_uploads_per_day, 1),
  }

  if (parsed.water_pressure_recover_psi <= parsed.water_pressure_low_psi) {
    throw new Error('Water pressure recover must be greater than low threshold')
  }
  if (parsed.oil_pressure_recover_psi <= parsed.oil_pressure_low_psi) {
    throw new Error('Oil pressure recover must be greater than low threshold')
  }
  if (parsed.battery_recover_v <= parsed.battery_low_v) {
    throw new Error('Battery recover must be greater than low threshold')
  }
  if (parsed.signal_recover_rssi_dbm <= parsed.signal_low_rssi_dbm) {
    throw new Error('Signal recover must be greater than low threshold')
  }

  return parsed
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function normalizeYamlNumericLiteral(rawLiteral: string): string | null {
  let literal = rawLiteral.trim()
  if (!literal) return null

  if (
    (literal.startsWith('"') && literal.endsWith('"')) ||
    (literal.startsWith("'") && literal.endsWith("'"))
  ) {
    literal = literal.slice(1, -1).trim()
  }
  if (!literal) return null

  const parsed = Number(literal.replace(/_/g, ''))
  if (!Number.isFinite(parsed)) return null
  return String(parsed)
}

function getYamlNumericLiteral(yamlText: string, key: string): string | null {
  const pattern = new RegExp(`^\\s*${escapeRegExp(key)}\\s*:\\s*([^#\\n]+?)\\s*(?:#.*)?$`, 'm')
  const match = pattern.exec(yamlText)
  if (!match) return null
  return normalizeYamlNumericLiteral(String(match[1] ?? ''))
}

function syncImportantDraftFromYaml(
  yamlText: string,
  current: ImportantPolicyDraft | null,
): ImportantPolicyDraft | null {
  if (!current) return null
  const next: ImportantPolicyDraft = { ...current }
  for (const key of IMPORTANT_POLICY_KEYS) {
    const literal = getYamlNumericLiteral(yamlText, key)
    if (literal != null) next[key] = literal
  }
  return next
}

function setYamlNumericValue(yamlText: string, key: string, value: number): string {
  const pattern = new RegExp(`^(\\s*${escapeRegExp(key)}\\s*:\\s*)([^#\\n]*?)(\\s*(#.*)?)$`, 'm')
  if (!pattern.test(yamlText)) throw new Error(`Could not find '${key}' in edge policy YAML`)
  const formatted = Number.isInteger(value) ? String(Math.trunc(value)) : String(value)
  return yamlText.replace(pattern, (_m, prefix: string, _current: string, suffix: string | undefined) => {
    return `${prefix}${formatted}${suffix ?? ''}`
  })
}

function applyImportantDraftToYaml(yamlText: string, draft: ParsedPolicyDraft): string {
  let next = yamlText
  for (const [key, value] of Object.entries(draft)) {
    next = setYamlNumericValue(next, key, value)
  }
  return next
}

function Callout(props: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border bg-muted/30 p-3">
      <div className="text-sm font-medium">{props.title}</div>
      <div className="mt-1 text-sm text-muted-foreground">{props.children}</div>
    </div>
  )
}

function KeyValue(props: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b py-2 last:border-b-0">
      <div className="text-sm text-muted-foreground">{props.k}</div>
      <div className="text-sm font-medium">{props.v}</div>
    </div>
  )
}

function PolicyNumberField(props: {
  label: string
  value: string
  onChange: (value: string) => void
  unit?: string
  disabled?: boolean
}) {
  return (
    <div className="space-y-1">
      <Label>{props.label}</Label>
      <div className="flex items-center gap-2">
        <Input
          type="number"
          value={props.value}
          onChange={(e) => props.onChange(e.target.value)}
          disabled={props.disabled}
        />
        {props.unit ? <span className="w-10 text-xs text-muted-foreground">{props.unit}</span> : null}
      </div>
    </div>
  )
}

export function SettingsPage() {
  const { theme, setTheme, adminKey, setAdminKey, clearAdminKey, adminKeyPersisted } = useAppSettings()
  const { toast } = useToast()
  const qc = useQueryClient()
  const healthQ = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 60_000 })

  const adminEnabled = Boolean(healthQ.data?.features?.admin?.enabled)
  const adminAuthMode = String(healthQ.data?.features?.admin?.auth_mode ?? 'key').toLowerCase()
  const { adminAccess, adminCred, keyRequired, keyValidating, keyInvalid } = useAdminAccess({
    adminEnabled,
    adminAuthMode,
    adminKey,
  })
  const envName = String(healthQ.data?.env ?? '').toLowerCase()
  const allowPersist = envName === 'dev'

  const [draftKey, setDraftKey] = React.useState(adminKey)
  const [destinationName, setDestinationName] = React.useState('')
  const [destinationKind, setDestinationKind] = React.useState<'discord' | 'telegram' | 'generic'>('discord')
  const [destinationUrl, setDestinationUrl] = React.useState('')

  const [importantDraft, setImportantDraft] = React.useState<ImportantPolicyDraft | null>(null)
  const [importantInitial, setImportantInitial] = React.useState<ImportantPolicyDraft | null>(null)
  const [policyYamlDraft, setPolicyYamlDraft] = React.useState('')
  const [policyYamlInitial, setPolicyYamlInitial] = React.useState('')

  React.useEffect(() => {
    setDraftKey(adminKey)
  }, [adminKey])

  const adminErrorMessage = React.useCallback(
    (error: unknown, fallback: string) => adminAccessHint(error, adminAuthMode) ?? fallback,
    [adminAuthMode],
  )

  const destinationsQ = useQuery({
    queryKey: ['admin', 'notificationDestinations'],
    queryFn: () => api.admin.notificationDestinations(adminCred),
    enabled: healthQ.isSuccess && adminAccess,
    staleTime: 30_000,
  })

  const telemetryQ = useQuery({
    queryKey: ['telemetryContract'],
    queryFn: api.telemetryContract,
    enabled: healthQ.isSuccess && adminAccess,
    staleTime: 30_000,
  })

  const policyQ = useQuery({
    queryKey: ['edgePolicyContract'],
    queryFn: api.edgePolicyContract,
    enabled: healthQ.isSuccess && adminAccess,
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
    const next = buildImportantPolicyDraft(policyQ.data)
    setImportantDraft(next)
    setImportantInitial(next)
  }, [policyQ.data?.policy_sha256])

  React.useEffect(() => {
    const yaml = policySourceQ.data?.yaml_text
    if (typeof yaml !== 'string') return
    setPolicyYamlDraft(yaml)
    setPolicyYamlInitial(yaml)
  }, [policySourceQ.data?.yaml_text])

  React.useEffect(() => {
    setImportantDraft((prev) => syncImportantDraftFromYaml(policyYamlDraft, prev ?? importantInitial))
  }, [policyYamlDraft, importantInitial])

  const createDestinationMutation = useMutation({
    mutationFn: async () => {
      const name = destinationName.trim()
      const webhook_url = destinationUrl.trim()
      if (!name) throw new Error('Name is required')
      if (!webhook_url) throw new Error('Webhook URL is required')
      return await api.admin.createNotificationDestination(adminCred, {
        name,
        channel: 'webhook',
        kind: destinationKind,
        webhook_url,
        enabled: true,
      })
    },
    onSuccess: () => {
      setDestinationName('')
      setDestinationUrl('')
      setDestinationKind('discord')
      toast({ title: 'Webhook destination added', variant: 'success' })
      qc.invalidateQueries({ queryKey: ['admin', 'notificationDestinations'] })
    },
    onError: (e) => {
      toast({
        title: 'Failed to add webhook destination',
        description: adminErrorMessage(e, 'Unable to add webhook destination.'),
        variant: 'error',
      })
    },
  })

  const toggleDestinationMutation = useMutation({
    mutationFn: async (destination: NotificationDestinationOut) =>
      await api.admin.updateNotificationDestination(adminCred, destination.id, {
        enabled: !destination.enabled,
      }),
    onSuccess: (updated) => {
      toast({
        title: updated.enabled ? 'Destination enabled' : 'Destination disabled',
        description: updated.name,
        variant: 'success',
      })
      qc.invalidateQueries({ queryKey: ['admin', 'notificationDestinations'] })
    },
    onError: (e) => {
      toast({
        title: 'Failed to update destination',
        description: adminErrorMessage(e, 'Unable to update destination.'),
        variant: 'error',
      })
    },
  })

  const deleteDestinationMutation = useMutation({
    mutationFn: async (destination: NotificationDestinationOut) =>
      await api.admin.deleteNotificationDestination(adminCred, destination.id),
    onSuccess: (deleted) => {
      toast({ title: 'Destination removed', description: deleted.name, variant: 'default' })
      qc.invalidateQueries({ queryKey: ['admin', 'notificationDestinations'] })
    },
    onError: (e) => {
      toast({
        title: 'Failed to remove destination',
        description: adminErrorMessage(e, 'Unable to remove destination.'),
        variant: 'error',
      })
    },
  })

  const validateAdminKeyMutation = useMutation({
    mutationFn: async (args: { key: string; persist: boolean }) => {
      const key = args.key.trim()
      if (!key) throw new Error('Enter an admin key first.')
      await api.admin.events(key, { limit: 1 })
      return { key, persist: args.persist }
    },
    onSuccess: ({ key, persist }) => {
      setAdminKey(key, { persist })
      qc.invalidateQueries({ queryKey: ['admin'] })
      if (persist) {
        toast({
          title: 'Admin key persisted',
          description: 'Validated and stored in browser storage on this machine. Do not use on shared or unmanaged devices.',
          variant: 'warning',
          durationMs: 7000,
        })
      } else {
        toast({
          title: 'Admin key saved',
          description: 'Validated and stored for this session.',
          variant: 'success',
        })
      }
    },
    onError: (e, vars) => {
      toast({
        title: vars.persist ? 'Admin key not persisted' : 'Admin key not saved',
        description: adminErrorMessage(e, (e as Error).message || 'Unable to validate admin key.'),
        variant: 'error',
      })
    },
  })

  const saveImportantMutation = useMutation({
    mutationFn: async () => {
      if (!adminAccess) throw new Error('Admin access required')
      if (!importantDraft) throw new Error('Policy values are not loaded')
      if (!policyYamlDraft.trim()) throw new Error('Policy YAML is not loaded')

      const parsed = parseImportantPolicyDraft(importantDraft)
      const updatedYaml = applyImportantDraftToYaml(policyYamlDraft, parsed)
      await api.admin.updateEdgePolicyContract(adminCred, { yaml_text: updatedYaml })
      return { updatedYaml, updatedDraft: { ...importantDraft } }
    },
    onSuccess: ({ updatedYaml, updatedDraft }) => {
      setPolicyYamlDraft(updatedYaml)
      setPolicyYamlInitial(updatedYaml)
      setImportantDraft(updatedDraft)
      setImportantInitial(updatedDraft)
      toast({ title: 'Important policy values saved', variant: 'success' })
      qc.invalidateQueries({ queryKey: ['edgePolicyContract'] })
      qc.invalidateQueries({ queryKey: ['admin', 'edgePolicyContractSource'] })
    },
    onError: (e) => {
      toast({
        title: 'Failed to save policy values',
        description: adminErrorMessage(e, (e as Error).message || 'Unable to save policy values.'),
        variant: 'error',
      })
    },
  })

  const saveYamlMutation = useMutation({
    mutationFn: async () => {
      if (!adminAccess) throw new Error('Admin access required')
      return await api.admin.updateEdgePolicyContract(adminCred, { yaml_text: policyYamlDraft })
    },
    onSuccess: () => {
      setPolicyYamlInitial(policyYamlDraft)
      const synced = syncImportantDraftFromYaml(policyYamlDraft, importantDraft ?? importantInitial)
      if (synced) {
        setImportantDraft(synced)
        setImportantInitial(synced)
      }
      toast({ title: 'Edge policy contract saved', variant: 'success' })
      qc.invalidateQueries({ queryKey: ['edgePolicyContract'] })
      qc.invalidateQueries({ queryKey: ['admin', 'edgePolicyContractSource'] })
    },
    onError: (e) => {
      toast({
        title: 'Failed to save edge policy YAML',
        description: adminErrorMessage(e, (e as Error).message || 'Unable to save edge policy YAML.'),
        variant: 'error',
      })
    },
  })

  const importantDirty = !policyDraftEqual(importantDraft, importantInitial)
  const yamlDirty = policyYamlDraft !== policyYamlInitial

  const policyAccessHint = React.useMemo(
    () => adminAccessHint(policyQ.error, adminAuthMode),
    [policyQ.error, adminAuthMode],
  )
  const sourceAccessHint = React.useMemo(
    () => adminAccessHint(policySourceQ.error, adminAuthMode),
    [policySourceQ.error, adminAuthMode],
  )
  const importantSaveAccessHint = React.useMemo(
    () => adminAccessHint(saveImportantMutation.error, adminAuthMode),
    [saveImportantMutation.error, adminAuthMode],
  )
  const yamlSaveAccessHint = React.useMemo(
    () => adminAccessHint(saveYamlMutation.error, adminAuthMode),
    [saveYamlMutation.error, adminAuthMode],
  )

  const setImportantField = React.useCallback((key: keyof ImportantPolicyDraft, value: string) => {
    setImportantDraft((prev) => (prev ? { ...prev, [key]: value } : prev))
  }, [])

  const telemetryContract = telemetryQ.data
  const policyContract = policyQ.data

  const telemetryRows = React.useMemo<MetricRow[]>(() => {
    if (!telemetryContract) return []
    return Object.entries(telemetryContract.metrics)
      .map(([key, m]) => ({
        key,
        type: m.type,
        unit: m.unit ?? '—',
        description: m.description ?? '—',
      }))
      .sort((a, b) => a.key.localeCompare(b.key))
  }, [telemetryContract])

  const telemetryCols = React.useMemo<ColumnDef<MetricRow>[]>(() => {
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
    if (!policyContract) return []
    return Object.entries(policyContract.delta_thresholds)
      .map(([key, threshold]) => ({ key, threshold }))
      .sort((a, b) => a.key.localeCompare(b.key))
  }, [policyContract])

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
      title="Settings"
      description="UI preferences and administrative access controls."
      actions={
        <div className="flex items-center gap-2">
          {healthQ.data ? <Badge variant="outline">env: {healthQ.data.env}</Badge> : null}
        </div>
      }
    >
      <div className="space-y-6">
        <div className="grid items-start gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Appearance</CardTitle>
              <CardDescription>Manage interface appearance.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium">Theme</div>
                  <div className="text-xs text-muted-foreground">Current: {theme}</div>
                </div>
                <Button variant="outline" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
                  Switch to {theme === 'dark' ? 'light' : 'dark'}
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Admin access</CardTitle>
              <CardDescription>
                Configure access to <code className="font-mono">/api/v1/admin/*</code> audit pages (ingestions, drift, notifications, exports).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {!healthQ.isSuccess ? (
                <div className="space-y-2">
                  <Badge variant="outline">checking…</Badge>
                  <div className="text-sm text-muted-foreground">Checking server capabilities…</div>
                </div>
              ) : !adminEnabled ? (
                <div className="space-y-2">
                  <Badge variant="outline">admin routes disabled</Badge>
                  <div className="text-sm text-muted-foreground">
                    This deployment was configured with <code className="font-mono">ENABLE_ADMIN_ROUTES=0</code>.
                    Use the dedicated admin service (recommended) or enable admin routes for this service.
                  </div>
                </div>
              ) : adminAuthMode === 'none' ? (
                <div className="space-y-2">
                  <Badge variant="success">admin protected by IAM</Badge>
                  <div className="text-sm text-muted-foreground">
                    This deployment is configured with <code className="font-mono">ADMIN_AUTH_MODE=none</code>, meaning admin
                    endpoints trust an infrastructure perimeter (Cloud Run IAM / IAP / VPN). No shared admin key is required
                    in the browser.
                  </div>
                </div>
              ) : (
                <>
                  <div className="space-y-2">
                    <Label>Admin key</Label>
                    <Input
                      type="password"
                      value={draftKey}
                      onChange={(e) => setDraftKey(e.target.value)}
                      placeholder="X-Admin-Key"
                    />
                    <div className="text-xs text-muted-foreground">
                      Must exactly match <code className="font-mono">ADMIN_API_KEY</code> on the server. Saved for the current browser
                      session by default; persistent browser storage is available only in development environments.
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      disabled={validateAdminKeyMutation.isPending}
                      onClick={() => {
                        validateAdminKeyMutation.mutate({ key: draftKey, persist: false })
                      }}
                    >
                      Save (session)
                    </Button>
                    <Button
                      variant="outline"
                      disabled={!allowPersist || validateAdminKeyMutation.isPending}
                      onClick={() => {
                        validateAdminKeyMutation.mutate({ key: draftKey, persist: true })
                      }}
                    >
                      Save + persist
                    </Button>
                    <Button
                      variant="destructive"
                      onClick={() => {
                        clearAdminKey()
                        toast({ title: 'Admin key cleared', variant: 'default' })
                      }}
                    >
                      Clear
                    </Button>
                    {keyValidating ? (
                      <Badge variant="secondary" className="ml-auto">
                        validating…
                      </Badge>
                    ) : adminAccess ? (
                      <Badge variant="success" className="ml-auto">
                        enabled{adminKeyPersisted ? ' (persisted)' : ''}
                      </Badge>
                    ) : keyInvalid ? (
                      <Badge variant="destructive" className="ml-auto">
                        invalid key
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="ml-auto">
                        disabled
                      </Badge>
                    )}
                  </div>

                  {!allowPersist ? (
                    <div className="text-xs text-muted-foreground">
                      Persistent browser storage for admin keys is disabled when <code className="font-mono">APP_ENV</code> is not
                      <code className="font-mono"> dev</code>.
                    </div>
                  ) : null}

                  <div className="text-xs text-muted-foreground">
                    If you are deploying publicly, do not expose the admin key to browsers. Instead, keep admin endpoints
                    private (Cloud Run IAM/IAP) or use a separate admin service.
                  </div>
                </>
              )}

              {healthQ.isSuccess && adminEnabled ? (
                <div className="space-y-3 border-t pt-4">
                  <div className="text-sm font-medium">Notification webhooks</div>
                  <div className="text-xs text-muted-foreground">
                    Create one or more webhook destinations for alert delivery. Each enabled destination receives routed notifications.
                  </div>

                  {!adminAccess ? (
                    <div className="text-sm text-muted-foreground">
                      {keyRequired
                        ? 'Configure an admin key above to manage webhook destinations.'
                        : keyValidating
                          ? 'Validating admin key…'
                          : 'The configured admin key is invalid. Update it above to manage webhook destinations.'}
                    </div>
                  ) : (
                    <>
                      <div className="space-y-2 rounded-md border bg-background p-3">
                        <div className="grid gap-2">
                          <div className="space-y-1">
                            <Label>Destination name</Label>
                            <Input
                              value={destinationName}
                              onChange={(e) => setDestinationName(e.target.value)}
                              placeholder="Primary on-call webhook"
                            />
                          </div>
                          <div className="space-y-1">
                            <Label>Webhook URL</Label>
                            <Input
                              value={destinationUrl}
                              onChange={(e) => setDestinationUrl(e.target.value)}
                              placeholder="https://hooks.example.com/services/..."
                            />
                            {destinationKind === 'telegram' ? (
                              <div className="text-xs text-muted-foreground">
                                For Telegram, include <code className="font-mono">chat_id</code> in the URL query string.
                              </div>
                            ) : null}
                          </div>
                          <div className="space-y-1">
                            <Label>Payload format</Label>
                            <div className="flex flex-wrap items-center gap-2">
                              <Button
                                type="button"
                                size="sm"
                                variant={destinationKind === 'discord' ? 'default' : 'outline'}
                                onClick={() => setDestinationKind('discord')}
                              >
                                Discord
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant={destinationKind === 'telegram' ? 'default' : 'outline'}
                                onClick={() => setDestinationKind('telegram')}
                              >
                                Telegram
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant={destinationKind === 'generic' ? 'default' : 'outline'}
                                onClick={() => setDestinationKind('generic')}
                              >
                                Generic
                              </Button>
                            </div>
                          </div>
                        </div>
                        <Button
                          onClick={() => createDestinationMutation.mutate()}
                          disabled={createDestinationMutation.isPending}
                        >
                          Add webhook destination
                        </Button>
                      </div>

                      {destinationsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading destinations…</div> : null}
                      {destinationsQ.isError ? (
                        <Callout title="Access guidance">
                          {adminErrorMessage(destinationsQ.error, 'Unable to load webhook destinations. Verify admin access and retry.')}
                        </Callout>
                      ) : null}

                      {!destinationsQ.isLoading && !destinationsQ.isError ? (
                        destinationsQ.data && destinationsQ.data.length > 0 ? (
                          <div className="space-y-2">
                            {destinationsQ.data.map((d) => (
                              <div key={d.id} className="rounded-md border bg-background p-3">
                                <div className="flex flex-wrap items-center gap-2">
                                  <div className="text-sm font-medium">{d.name}</div>
                                  <Badge variant="outline">{d.kind}</Badge>
                                  {d.enabled ? <Badge variant="success">enabled</Badge> : <Badge variant="outline">disabled</Badge>}
                                  <div className="ml-auto text-xs text-muted-foreground">{d.webhook_url_masked}</div>
                                </div>
                                <div className="mt-2 flex flex-wrap items-center gap-2">
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    disabled={toggleDestinationMutation.isPending}
                                    onClick={() => toggleDestinationMutation.mutate(d)}
                                  >
                                    {d.enabled ? 'Disable' : 'Enable'}
                                  </Button>
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant="destructive"
                                    disabled={deleteDestinationMutation.isPending}
                                    onClick={() => deleteDestinationMutation.mutate(d)}
                                  >
                                    Remove
                                  </Button>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="text-sm text-muted-foreground">
                            No UI-configured webhook destinations yet. If <code className="font-mono">ALERT_WEBHOOK_URL</code> is set in
                            the deployment environment, it remains the fallback destination.
                          </div>
                        )
                      ) : null}
                    </>
                  )}
                </div>
              ) : null}
            </CardContent>
          </Card>
        </div>

        {healthQ.isSuccess && adminEnabled && adminAccess ? (
          <>
            <Card>
              <CardHeader>
                <CardTitle>Contracts</CardTitle>
                <CardDescription>Telemetry schema and edge policy details for this deployment.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {telemetryQ.isLoading || policyQ.isLoading ? (
                  <div className="text-sm text-muted-foreground">Loading contract details…</div>
                ) : null}
                {telemetryQ.isError ? (
                  <Callout title="Access guidance">
                    {adminErrorMessage(telemetryQ.error, 'Unable to load telemetry contract. Verify admin access and retry.')}
                  </Callout>
                ) : null}
                {policyQ.isError ? (
                  <Callout title="Access guidance">
                    {adminErrorMessage(policyQ.error, 'Unable to load edge policy contract. Verify admin access and retry.')}
                  </Callout>
                ) : null}

                {telemetryContract ? (
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="text-sm font-medium">Telemetry contract</div>
                      <Badge variant="outline">version: v{telemetryContract.version}</Badge>
                      <Badge variant="secondary">sha: {telemetryContract.sha256.slice(0, 12)}…</Badge>
                      <Badge variant="outline">metrics: {Object.keys(telemetryContract.metrics).length}</Badge>
                    </div>
                    <DataTable<MetricRow>
                      data={telemetryRows}
                      columns={telemetryCols}
                      height={360}
                      enableSorting
                      initialSorting={[{ id: 'key', desc: false }]}
                      emptyState="No telemetry contract loaded."
                    />
                  </div>
                ) : null}

                {policyContract ? (
                  <div className="space-y-4">
                    <Separator />
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="text-sm font-medium">Edge policy contract</div>
                      <Badge variant="outline">policy: {policyContract.policy_version}</Badge>
                      <Badge variant="secondary">sha: {policyContract.policy_sha256.slice(0, 12)}…</Badge>
                      <Badge variant="outline">cache: {policyContract.cache_max_age_s}s</Badge>
                    </div>

                    <div className="grid gap-6 lg:grid-cols-2">
                      <div>
                        <div className="text-sm font-medium">Reporting</div>
                        <div className="mt-2">
                          <KeyValue
                            k="Sample interval"
                            v={<span className="font-mono text-xs">{policyContract.reporting.sample_interval_s}s</span>}
                          />
                          <KeyValue
                            k="Heartbeat"
                            v={<span className="font-mono text-xs">{policyContract.reporting.heartbeat_interval_s}s</span>}
                          />
                          <KeyValue
                            k="Alert sample interval"
                            v={<span className="font-mono text-xs">{policyContract.reporting.alert_sample_interval_s}s</span>}
                          />
                          <KeyValue
                            k="Alert report interval"
                            v={<span className="font-mono text-xs">{policyContract.reporting.alert_report_interval_s}s</span>}
                          />
                          <KeyValue
                            k="Max points / batch"
                            v={<span className="font-mono text-xs">{policyContract.reporting.max_points_per_batch}</span>}
                          />
                        </div>
                      </div>

                      <div>
                        <div className="text-sm font-medium">Alert thresholds</div>
                        <div className="mt-2">
                          <KeyValue
                            k="Water pressure low"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.water_pressure_low_psi} psi</span>}
                          />
                          <KeyValue
                            k="Water recover"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.water_pressure_recover_psi} psi</span>}
                          />
                          <KeyValue
                            k="Oil pressure low"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.oil_pressure_low_psi} psi</span>}
                          />
                          <KeyValue
                            k="Oil pressure recover"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.oil_pressure_recover_psi} psi</span>}
                          />
                          <KeyValue
                            k="Oil level low"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.oil_level_low_pct}%</span>}
                          />
                          <KeyValue
                            k="Oil level recover"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.oil_level_recover_pct}%</span>}
                          />
                          <KeyValue
                            k="Drip oil low"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.drip_oil_level_low_pct}%</span>}
                          />
                          <KeyValue
                            k="Drip oil recover"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.drip_oil_level_recover_pct}%</span>}
                          />
                          <KeyValue
                            k="Oil life low"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.oil_life_low_pct}%</span>}
                          />
                          <KeyValue
                            k="Oil life recover"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.oil_life_recover_pct}%</span>}
                          />
                          <KeyValue
                            k="Battery low"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.battery_low_v} V</span>}
                          />
                          <KeyValue
                            k="Battery recover"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.battery_recover_v} V</span>}
                          />
                          <KeyValue
                            k="Signal low"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.signal_low_rssi_dbm} dBm</span>}
                          />
                          <KeyValue
                            k="Signal recover"
                            v={<span className="font-mono text-xs">{policyContract.alert_thresholds.signal_recover_rssi_dbm} dBm</span>}
                          />
                        </div>
                      </div>
                    </div>

                    <div>
                      <div className="text-sm font-medium">Delta thresholds</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        Edge devices can suppress sends when metric values change less than these deltas.
                      </div>
                      <div className="mt-2">
                        <DataTable<DeltaRow>
                          data={deltaRows}
                          columns={deltaCols}
                          height={320}
                          enableSorting
                          initialSorting={[{ id: 'key', desc: false }]}
                          emptyState="No delta thresholds."
                        />
                      </div>
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Contract policy controls</CardTitle>
                <CardDescription>
                  Edit high-signal edge policy settings here, or use the full YAML editor for advanced updates.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                {policyQ.isLoading || policySourceQ.isLoading ? (
                  <div className="text-sm text-muted-foreground">Loading policy controls…</div>
                ) : null}
                {policyQ.isError ? (
                  <Callout title="Access guidance">
                    {adminErrorMessage(policyQ.error, 'Unable to load policy contract. Verify admin access and retry.')}
                  </Callout>
                ) : null}
                {policySourceQ.isError ? (
                  <Callout title="Access guidance">
                    {adminErrorMessage(policySourceQ.error, 'Unable to load policy YAML source. Verify admin access and retry.')}
                  </Callout>
                ) : null}
                {policyAccessHint ? <Callout title="Access guidance">{policyAccessHint}</Callout> : null}
                {sourceAccessHint ? <Callout title="Access guidance">{sourceAccessHint}</Callout> : null}

                {importantDraft ? (
                  <>
                    <div className="grid gap-4 xl:grid-cols-2">
                      <div className="space-y-3 rounded-md border bg-background p-4">
                        <div className="text-sm font-medium">Reporting cadence</div>
                        <div className="grid gap-3 sm:grid-cols-2">
                          <PolicyNumberField
                            label="Sample interval"
                            unit="s"
                            value={importantDraft.sample_interval_s}
                            onChange={(v) => setImportantField('sample_interval_s', v)}
                          />
                          <PolicyNumberField
                            label="Heartbeat interval"
                            unit="s"
                            value={importantDraft.heartbeat_interval_s}
                            onChange={(v) => setImportantField('heartbeat_interval_s', v)}
                          />
                          <PolicyNumberField
                            label="Alert sample interval"
                            unit="s"
                            value={importantDraft.alert_sample_interval_s}
                            onChange={(v) => setImportantField('alert_sample_interval_s', v)}
                          />
                          <PolicyNumberField
                            label="Alert report interval"
                            unit="s"
                            value={importantDraft.alert_report_interval_s}
                            onChange={(v) => setImportantField('alert_report_interval_s', v)}
                          />
                          <PolicyNumberField
                            label="Max points per batch"
                            value={importantDraft.max_points_per_batch}
                            onChange={(v) => setImportantField('max_points_per_batch', v)}
                          />
                        </div>
                      </div>

                      <div className="space-y-3 rounded-md border bg-background p-4">
                        <div className="text-sm font-medium">Alert thresholds</div>
                        <div className="grid gap-3 sm:grid-cols-2">
                          <PolicyNumberField
                            label="Water pressure low"
                            unit="psi"
                            value={importantDraft.water_pressure_low_psi}
                            onChange={(v) => setImportantField('water_pressure_low_psi', v)}
                          />
                          <PolicyNumberField
                            label="Water pressure recover"
                            unit="psi"
                            value={importantDraft.water_pressure_recover_psi}
                            onChange={(v) => setImportantField('water_pressure_recover_psi', v)}
                          />
                          <PolicyNumberField
                            label="Oil pressure low"
                            unit="psi"
                            value={importantDraft.oil_pressure_low_psi}
                            onChange={(v) => setImportantField('oil_pressure_low_psi', v)}
                          />
                          <PolicyNumberField
                            label="Oil pressure recover"
                            unit="psi"
                            value={importantDraft.oil_pressure_recover_psi}
                            onChange={(v) => setImportantField('oil_pressure_recover_psi', v)}
                          />
                          <PolicyNumberField
                            label="Battery low"
                            unit="V"
                            value={importantDraft.battery_low_v}
                            onChange={(v) => setImportantField('battery_low_v', v)}
                          />
                          <PolicyNumberField
                            label="Battery recover"
                            unit="V"
                            value={importantDraft.battery_recover_v}
                            onChange={(v) => setImportantField('battery_recover_v', v)}
                          />
                          <PolicyNumberField
                            label="Signal low"
                            unit="dBm"
                            value={importantDraft.signal_low_rssi_dbm}
                            onChange={(v) => setImportantField('signal_low_rssi_dbm', v)}
                          />
                          <PolicyNumberField
                            label="Signal recover"
                            unit="dBm"
                            value={importantDraft.signal_recover_rssi_dbm}
                            onChange={(v) => setImportantField('signal_recover_rssi_dbm', v)}
                          />
                        </div>
                      </div>
                    </div>

                    <div className="rounded-md border bg-background p-4">
                      <div className="mb-3 text-sm font-medium">Cost caps</div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <PolicyNumberField
                          label="Max bytes per day"
                          value={importantDraft.max_bytes_per_day}
                          onChange={(v) => setImportantField('max_bytes_per_day', v)}
                        />
                        <PolicyNumberField
                          label="Max media uploads per day"
                          value={importantDraft.max_media_uploads_per_day}
                          onChange={(v) => setImportantField('max_media_uploads_per_day', v)}
                        />
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        onClick={() => saveImportantMutation.mutate()}
                        disabled={!importantDirty || saveImportantMutation.isPending || !policyYamlDraft.trim()}
                      >
                        Save policy values
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => setImportantDraft(importantInitial)}
                        disabled={!importantDirty || saveImportantMutation.isPending}
                      >
                        Reset values
                      </Button>
                      {importantDirty ? <Badge variant="outline">unsaved values</Badge> : null}
                    </div>
                    {saveImportantMutation.isError ? (
                      <Callout title="Access guidance">
                        {adminErrorMessage(saveImportantMutation.error, 'Unable to save policy values.')}
                      </Callout>
                    ) : null}
                    {importantSaveAccessHint ? <Callout title="Access guidance">{importantSaveAccessHint}</Callout> : null}
                  </>
                ) : null}

                <Separator />

                <div className="space-y-3">
                  <div>
                    <div className="text-sm font-medium">Edit edge policy contract (YAML)</div>
                    <div className="text-xs text-muted-foreground">
                      Use this for full-contract edits beyond the high-signal controls above.
                    </div>
                  </div>

                  <Textarea
                    value={policyYamlDraft}
                    onChange={(e) => setPolicyYamlDraft(e.target.value)}
                    className="min-h-[360px] font-mono text-xs"
                    spellCheck={false}
                  />

                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      onClick={() => saveYamlMutation.mutate()}
                      disabled={!yamlDirty || saveYamlMutation.isPending}
                    >
                      Save contract YAML
                    </Button>
                    <Button
                      variant="outline"
                      onClick={() => setPolicyYamlDraft(policyYamlInitial)}
                      disabled={!yamlDirty || saveYamlMutation.isPending}
                    >
                      Reset YAML
                    </Button>
                    {yamlDirty ? <Badge variant="outline">unsaved YAML</Badge> : null}
                  </div>
                  {saveYamlMutation.isError ? (
                    <Callout title="Access guidance">
                      {adminErrorMessage(saveYamlMutation.error, 'Unable to save edge policy YAML.')}
                    </Callout>
                  ) : null}
                  {yamlSaveAccessHint ? <Callout title="Access guidance">{yamlSaveAccessHint}</Callout> : null}
                </div>
              </CardContent>
            </Card>
          </>
        ) : null}
      </div>
    </Page>
  )
}
