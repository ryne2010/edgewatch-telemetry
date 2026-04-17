export type DeviceOut = {
  device_id: string
  display_name: string
  heartbeat_interval_s: number
  offline_after_s: number
  last_seen_at: string | null
  enabled: boolean
  operation_mode: 'active' | 'sleep' | 'disabled'
  sleep_poll_interval_s: number
  runtime_power_mode: 'continuous' | 'eco' | 'deep_sleep'
  deep_sleep_backend: 'auto' | 'pi5_rtc' | 'external_supervisor' | 'none'
  alerts_muted_until: string | null
  alerts_muted_reason: string | null
  ota_channel: string
  ota_updates_enabled: boolean
  ota_busy_reason: string | null
  ota_is_development: boolean
  ota_locked_manifest_id: string | null
  status: 'online' | 'offline' | 'unknown' | 'sleep' | 'disabled'
  seconds_since_last_seen: number | null
}

export type CreateDeviceIn = {
  device_id: string
  display_name?: string
  token: string
  heartbeat_interval_s?: number
  offline_after_s?: number
  owner_emails?: string[]
  ota_channel?: string
  ota_updates_enabled?: boolean
  ota_busy_reason?: string | null
  ota_is_development?: boolean
  ota_locked_manifest_id?: string | null
}

export type UpdateDeviceIn = {
  display_name?: string
  token?: string
  heartbeat_interval_s?: number
  offline_after_s?: number
  enabled?: boolean
  ota_channel?: string
  ota_updates_enabled?: boolean
  ota_busy_reason?: string | null
  ota_is_development?: boolean
  ota_locked_manifest_id?: string | null
}

export type DeviceSummaryOut = {
  device_id: string
  display_name: string
  heartbeat_interval_s: number
  offline_after_s: number
  last_seen_at: string | null
  enabled: boolean
  operation_mode: 'active' | 'sleep' | 'disabled'
  sleep_poll_interval_s: number
  runtime_power_mode: 'continuous' | 'eco' | 'deep_sleep'
  deep_sleep_backend: 'auto' | 'pi5_rtc' | 'external_supervisor' | 'none'
  alerts_muted_until: string | null
  alerts_muted_reason: string | null
  ota_channel: string
  ota_updates_enabled: boolean
  ota_busy_reason: string | null
  ota_is_development: boolean
  ota_locked_manifest_id: string | null
  status: 'online' | 'offline' | 'unknown' | 'sleep' | 'disabled'
  seconds_since_last_seen: number | null
  latest_telemetry_at: string | null
  latest_message_id: string | null
  metrics: Record<string, unknown>
}

export const FLEET_VITALS_SUMMARY_METRICS = [
  'microphone_level_db',
  'power_input_v',
  'power_input_a',
  'power_input_w',
  'power_source',
  'power_input_out_of_range',
  'power_unsustainable',
  'power_saver_active',
  'water_pressure_psi',
  'oil_pressure_psi',
  'oil_level_pct',
  'drip_oil_level_pct',
  'oil_life_pct',
  'temperature_c',
  'humidity_pct',
  'battery_v',
  'signal_rssi_dbm',
] as const

export const FLEET_LOCATION_SUMMARY_METRICS = [
  'latitude',
  'longitude',
  'lat',
  'lon',
  'lng',
  'gps_latitude',
  'gps_longitude',
  'location_lat',
  'location_lon',
] as const

export type DeviceControlsOut = {
  device_id: string
  operation_mode: 'active' | 'sleep' | 'disabled'
  sleep_poll_interval_s: number
  runtime_power_mode: 'continuous' | 'eco' | 'deep_sleep'
  deep_sleep_backend: 'auto' | 'pi5_rtc' | 'external_supervisor' | 'none'
  disable_requires_manual_restart: boolean
  alerts_muted_until: string | null
  alerts_muted_reason: string | null
  pending_command_count: number
  latest_pending_command_expires_at: string | null
  latest_pending_operation_mode: 'active' | 'sleep' | 'disabled' | null
  latest_pending_shutdown_requested: boolean
  latest_pending_shutdown_grace_s: number | null
}

export type DeviceOperationControlUpdateIn = {
  operation_mode: 'active' | 'sleep' | 'disabled'
  sleep_poll_interval_s?: number
  runtime_power_mode?: 'continuous' | 'eco' | 'deep_sleep'
  deep_sleep_backend?: 'auto' | 'pi5_rtc' | 'external_supervisor' | 'none'
}

export type DeviceAlertsControlUpdateIn = {
  alerts_muted_until?: string | null
  alerts_muted_reason?: string | null
}

export type AdminDeviceShutdownIn = {
  reason: string
  shutdown_grace_s?: number
}

export type DeviceAccessGrantOut = {
  device_id: string
  principal_email: string
  access_role: 'viewer' | 'operator' | 'owner'
  created_at: string
  updated_at: string
}

export type FleetOut = {
  id: string
  name: string
  description: string | null
  default_ota_channel: string
  created_at: string
  updated_at: string
  device_count: number
}

export type FleetCreateIn = {
  name: string
  description?: string | null
  default_ota_channel?: string
}

export type FleetUpdateIn = {
  description?: string | null
  default_ota_channel?: string
}

export type FleetMembershipOut = {
  fleet_id: string
  device_id: string
  added_at: string
}

export type FleetAccessGrantOut = {
  fleet_id: string
  principal_email: string
  access_role: 'viewer' | 'operator' | 'owner'
  created_at: string
  updated_at: string
}

export type ReleaseManifestOut = {
  id: string
  git_tag: string
  commit_sha: string
  update_type: 'application_bundle' | 'asset_bundle' | 'system_image'
  artifact_uri: string
  artifact_size: number
  artifact_sha256: string
  artifact_signature: string
  artifact_signature_scheme: 'none' | 'openssl_rsa_sha256'
  compatibility: Record<string, unknown>
  signature: string
  signature_key_id: string
  constraints: Record<string, unknown>
  created_by: string
  created_at: string
  status: string
}

export type ReleaseManifestCreateIn = {
  git_tag: string
  commit_sha: string
  update_type?: 'application_bundle' | 'asset_bundle' | 'system_image'
  artifact_uri: string
  artifact_size: number
  artifact_sha256: string
  artifact_signature?: string
  artifact_signature_scheme?: 'none' | 'openssl_rsa_sha256'
  compatibility?: Record<string, unknown>
  signature: string
  signature_key_id: string
  constraints?: Record<string, unknown>
  status?: string
}

export type ReleaseManifestUpdateIn = {
  status?: string
}

export type DeploymentTargetOut = {
  device_id: string
  stage_assigned: number
  status: string
  last_report_at: string | null
  failure_reason: string | null
  report_details: Record<string, unknown>
}

export type DeploymentEventOut = {
  id: string
  deployment_id: string
  event_type: string
  device_id: string | null
  details: Record<string, unknown>
  created_at: string
}

export type DeploymentOut = {
  id: string
  manifest_id: string
  strategy: Record<string, unknown>
  stage: number
  status: string
  halt_reason: string | null
  created_by: string
  created_at: string
  updated_at: string
  failure_rate_threshold: number
  no_quorum_timeout_s: number
  stage_timeout_s: number
  defer_rate_threshold: number
  command_expires_at: string
  power_guard_required: boolean
  health_timeout_s: number
  rollback_to_tag: string | null
  target_selector: Record<string, unknown>
  total_targets: number
  queued_targets: number
  in_progress_targets: number
  deferred_targets: number
  healthy_targets: number
  failed_targets: number
  rolled_back_targets: number
}

export type DeploymentDetailOut = DeploymentOut & {
  manifest: ReleaseManifestOut
  targets: DeploymentTargetOut[]
  events: DeploymentEventOut[]
}

export type DeploymentTargetPageOut = {
  items: DeploymentTargetOut[]
  total: number
  limit: number
  offset: number
}

export type DeploymentCreateIn = {
  manifest_id: string
  target_selector: {
    mode: 'all' | 'cohort' | 'labels' | 'explicit_ids' | 'channel'
    cohort?: string
    channel?: string
    labels?: Record<string, string>
    device_ids?: string[]
  }
  rollout_stages_pct?: number[]
  failure_rate_threshold?: number
  no_quorum_timeout_s?: number
  stage_timeout_s?: number
  defer_rate_threshold?: number
  health_timeout_s?: number
  command_ttl_s?: number
  power_guard_required?: boolean
  rollback_to_tag?: string | null
}

export type DeploymentActionOut = {
  id: string
  status: string
  stage: number
  halt_reason: string | null
  updated_at: string
}

export type AlertOut = {
  id: string
  device_id: string
  alert_type: string
  severity: string
  message: string
  created_at: string
  resolved_at: string | null
}

export type TimeseriesPoint = {
  bucket_ts: string
  value: number
}

export type TimeseriesMultiPoint = {
  bucket_ts: string
  values: Record<string, number | null>
}

export type TelemetryContractMetric = {
  type: string
  unit?: string | null
  description?: string | null
}

export type TelemetryContract = {
  version: string
  sha256: string
  metrics: Record<string, TelemetryContractMetric>
  profiles: Record<string, Record<string, unknown>>
}

export type EdgePolicyContractOut = {
  policy_version: string
  policy_sha256: string
  cache_max_age_s: number
  reporting: {
    sample_interval_s: number
    alert_sample_interval_s: number
    heartbeat_interval_s: number
    alert_report_interval_s: number

    max_points_per_batch: number
    buffer_max_points: number
    buffer_max_age_s: number

    backoff_initial_s: number
    backoff_max_s: number
  }
  delta_thresholds: Record<string, number>
  alert_thresholds: {
    microphone_offline_db: number
    microphone_offline_open_consecutive_samples: number
    microphone_offline_resolve_consecutive_samples: number

    water_pressure_low_psi: number
    water_pressure_recover_psi: number

    oil_pressure_low_psi: number
    oil_pressure_recover_psi: number

    oil_level_low_pct: number
    oil_level_recover_pct: number

    drip_oil_level_low_pct: number
    drip_oil_level_recover_pct: number

    oil_life_low_pct: number
    oil_life_recover_pct: number

    battery_low_v: number
    battery_recover_v: number

    signal_low_rssi_dbm: number
    signal_recover_rssi_dbm: number
  }
  cost_caps: {
    max_bytes_per_day: number
    max_snapshots_per_day: number
    max_media_uploads_per_day: number
  }
  power_management: {
    enabled: boolean
    mode: string
    input_warn_min_v: number
    input_warn_max_v: number
    input_critical_min_v: number
    input_critical_max_v: number
    sustainable_input_w: number
    unsustainable_window_s: number
    battery_trend_window_s: number
    battery_drop_warn_v: number
    saver_sample_interval_s: number
    saver_heartbeat_interval_s: number
    media_disabled_in_saver: boolean
  }
  operation_defaults: {
    default_sleep_poll_interval_s: number
    default_runtime_power_mode: 'continuous' | 'eco' | 'deep_sleep'
    default_deep_sleep_backend: 'auto' | 'pi5_rtc' | 'external_supervisor' | 'none'
    disable_requires_manual_restart: boolean
    admin_remote_shutdown_enabled: boolean
    shutdown_grace_s_default: number
    control_command_ttl_s: number
  }
}

export type EdgePolicyContractSourceOut = {
  policy_version: string
  yaml_text: string
}

export type EdgePolicyContractUpdateIn = {
  yaml_text: string
}

export type IngestionBatchOut = {
  id: string
  device_id: string
  received_at: string
  contract_version: string
  contract_hash: string
  points_submitted: number
  points_accepted: number
  duplicates: number
  points_quarantined: number
  client_ts_min: string | null
  client_ts_max: string | null
  unknown_metric_keys: string[]
  type_mismatch_keys: string[]
  drift_summary: Record<string, unknown>
  source: string
  pipeline_mode: string
  processing_status: string
}

export type IngestionBatchPageOut = {
  items: IngestionBatchOut[]
  total: number
  limit: number
  offset: number
}

export type DriftEventOut = {
  id: string
  batch_id: string
  device_id: string
  event_type: string
  action: string
  details: Record<string, unknown>
  created_at: string
}

export type DriftEventPageOut = {
  items: DriftEventOut[]
  total: number
  limit: number
  offset: number
}

export type NotificationEventOut = {
  id: string
  alert_id: string | null
  device_id: string
  source_kind: string
  source_id: string | null
  alert_type: string
  channel: string
  decision: string
  delivered: boolean
  reason: string
  payload: Record<string, unknown>
  created_at: string
}

export type NotificationEventPageOut = {
  items: NotificationEventOut[]
  total: number
  limit: number
  offset: number
}

export type NotificationDestinationOut = {
  id: string
  name: string
  channel: 'webhook' | string
  kind: 'generic' | 'slack' | 'discord' | 'telegram' | string
  source_types: string[]
  event_types: string[]
  enabled: boolean
  webhook_url_masked: string
  destination_fingerprint: string
  created_at: string
  updated_at: string
}

export type NotificationDestinationCreateIn = {
  name: string
  channel?: 'webhook'
  kind?: 'generic' | 'slack' | 'discord' | 'telegram'
  webhook_url: string
  source_types?: string[]
  event_types?: string[]
  enabled?: boolean
}

export type NotificationDestinationUpdateIn = {
  name?: string
  channel?: 'webhook'
  kind?: 'generic' | 'slack' | 'discord' | 'telegram'
  webhook_url?: string
  source_types?: string[]
  event_types?: string[]
  enabled?: boolean
}

export type DeviceProcedureDefinitionOut = {
  id: string
  name: string
  description: string | null
  request_schema: Record<string, unknown>
  response_schema: Record<string, unknown>
  timeout_s: number
  enabled: boolean
  created_by: string
  created_at: string
  updated_at: string
}

export type DeviceProcedureDefinitionCreateIn = {
  name: string
  description?: string | null
  request_schema?: Record<string, unknown>
  response_schema?: Record<string, unknown>
  timeout_s?: number
  enabled?: boolean
}

export type DeviceProcedureInvocationOut = {
  id: string
  device_id: string
  definition_id: string
  definition_name: string
  request_payload: Record<string, unknown>
  result_payload: Record<string, unknown> | null
  status: 'queued' | 'in_progress' | 'succeeded' | 'failed' | 'expired' | 'superseded'
  reason_code: string | null
  reason_detail: string | null
  requester_email: string
  issued_at: string
  expires_at: string
  acknowledged_at: string | null
  completed_at: string | null
  superseded_at: string | null
}

export type DeviceProcedureInvokeIn = {
  request_payload?: Record<string, unknown>
  ttl_s?: number
}

export type DeviceReportedStateItemOut = {
  key: string
  value_json: unknown
  schema_type: string | null
  updated_at: string
}

export type DeviceEventOut = {
  id: string
  device_id: string
  event_type: string
  severity: string
  source: string
  body: Record<string, unknown>
  created_at: string
}

export type OperatorSearchResultOut = {
  entity_type:
    | 'device'
    | 'fleet'
    | 'alert'
    | 'ingestion_batch'
    | 'drift_event'
    | 'device_event'
    | 'procedure_definition'
    | 'procedure_invocation'
    | 'deployment'
    | 'release_manifest'
    | 'admin_event'
    | 'notification_event'
    | 'notification_destination'
    | 'export_batch'
  entity_id: string
  title: string
  subtitle: string | null
  device_id: string | null
  created_at: string | null
  metadata: Record<string, unknown>
}

export type OperatorSearchPageOut = {
  items: OperatorSearchResultOut[]
  total: number
  limit: number
  offset: number
}

export type OperatorEventOut = {
  source_kind: 'alert' | 'notification_event' | 'device_event' | 'procedure_invocation' | 'deployment_event' | 'release_manifest_event' | 'admin_event'
  entity_id: string
  device_id: string | null
  event_name: string
  severity: string
  created_at: string
  payload: Record<string, unknown>
}

export type OperatorEventPageOut = {
  items: OperatorEventOut[]
  total: number
  limit: number
  offset: number
}

export type AdminEventOut = {
  id: string
  actor_email: string
  actor_subject: string | null
  action: string
  target_type: string
  target_device_id: string | null
  details: Record<string, unknown>
  request_id: string | null
  created_at: string
}

export type AdminEventPageOut = {
  items: AdminEventOut[]
  total: number
  limit: number
  offset: number
}

export type ExportBatchOut = {
  id: string
  started_at: string
  finished_at: string | null
  watermark_from: string | null
  watermark_to: string | null
  contract_version: string
  contract_hash: string
  gcs_uri: string | null
  row_count: number
  status: string
  error_message: string | null
}

export type ExportBatchPageOut = {
  items: ExportBatchOut[]
  total: number
  limit: number
  offset: number
}

export type MediaObjectOut = {
  id: string
  device_id: string
  camera_id: string
  message_id: string
  captured_at: string
  reason: string
  sha256: string
  bytes: number
  mime_type: string
  object_path: string
  gcs_uri: string | null
  local_path: string | null
  uploaded_at: string | null
  created_at: string
}

export type TelemetryPoint = {
  message_id: string
  device_id: string
  ts: string
  metrics: Record<string, unknown>
}

async function getJSON<T>(path: string, opts?: { headers?: Record<string, string> }): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts?.headers) {
    for (const [k, v] of Object.entries(opts.headers)) headers[k] = v
  }
  let res = await fetch(path, { headers })

  // If an intermediary returns a 304 (Not Modified), re-fetch bypassing caches
  // so callers always receive a JSON body.
  if (res.status === 304) {
    res = await fetch(path, { headers, cache: 'reload' })
  }
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${body ? ` - ${body}` : ''}`)
  }
  return res.json() as Promise<T>
}

async function sendJSON<T>(
  path: string,
  body: unknown,
  opts?: { method?: 'POST' | 'PATCH' | 'PUT' | 'DELETE'; headers?: Record<string, string> },
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
  }
  if (opts?.headers) {
    for (const [k, v] of Object.entries(opts.headers)) headers[k] = v
  }

  const res = await fetch(path, {
    method: opts?.method ?? 'POST',
    headers,
    body: JSON.stringify(body ?? {}),
  })

  if (!res.ok) {
    const txt = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${txt ? ` - ${txt}` : ''}`)
  }
  return res.json() as Promise<T>
}

async function getBlob(
  path: string,
  opts?: { headers?: Record<string, string>; cache?: RequestCache },
): Promise<Blob> {
  const headers: Record<string, string> = {}
  if (opts?.headers) {
    for (const [k, v] of Object.entries(opts.headers)) headers[k] = v
  }
  const res = await fetch(path, {
    headers,
    cache: opts?.cache ?? 'no-store',
  })

  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${body ? ` - ${body}` : ''}`)
  }
  return res.blob()
}

function adminHeaders(adminKey: string | null | undefined): Record<string, string> {
  let k = (adminKey ?? '').trim()
  const assignMatch = /^(?:export\s+)?admin_api_key\s*=\s*(.+)$/i.exec(k)
  if (assignMatch) k = assignMatch[1].trim()
  if ((k.startsWith('"') && k.endsWith('"')) || (k.startsWith("'") && k.endsWith("'"))) {
    k = k.slice(1, -1).trim()
  }
  return k ? { 'X-Admin-Key': k } : {}
}

function bearerHeaders(token: string | null | undefined): Record<string, string> {
  const t = (token ?? '').trim()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

export const api = {
  health: () =>
    getJSON<{
      ok: boolean
      env: string
      version?: string
      features?: {
        admin?: { enabled?: boolean; auth_mode?: string; iap_auth_enabled?: boolean }
        authz?: { enabled?: boolean; iap_default_role?: string; dev_principal_enabled?: boolean }
        docs?: { enabled?: boolean }
        otel?: { enabled?: boolean }
        ui?: { enabled?: boolean }
        routes?: { ingest?: boolean; read?: boolean; ota_updates?: boolean }
        ingest?: { pipeline_mode?: string }
        analytics_export?: { enabled?: boolean }
        retention?: { enabled?: boolean }
        limits?: {
          max_request_body_bytes?: number
          max_points_per_request?: number
          rate_limit_enabled?: boolean
          ingest_rate_limit_points_per_min?: number
        }
      }
    }>('/api/v1/health'),
  devices: () => getJSON<DeviceOut[]>('/api/v1/devices'),
  devicesSummary: (opts?: { metrics?: string[]; limitMetrics?: number }) => {
    const params = new URLSearchParams()
    for (const m of opts?.metrics ?? []) params.append('metrics', m)
    if (typeof opts?.limitMetrics === 'number') params.set('limit_metrics', String(opts.limitMetrics))
    const qs = params.toString()
    return getJSON<DeviceSummaryOut[]>(`/api/v1/devices/summary${qs ? `?${qs}` : ''}`)
  },
  device: (device_id: string) => getJSON<DeviceOut>(`/api/v1/devices/${encodeURIComponent(device_id)}`),
  deviceControls: {
    get: (device_id: string) =>
      getJSON<DeviceControlsOut>(`/api/v1/devices/${encodeURIComponent(device_id)}/controls`),
    updateOperation: (device_id: string, payload: DeviceOperationControlUpdateIn) =>
      sendJSON<DeviceControlsOut>(`/api/v1/devices/${encodeURIComponent(device_id)}/controls/operation`, payload, {
        method: 'PATCH',
      }),
    updateAlerts: (device_id: string, payload: DeviceAlertsControlUpdateIn) =>
      sendJSON<DeviceControlsOut>(`/api/v1/devices/${encodeURIComponent(device_id)}/controls/alerts`, payload, {
        method: 'PATCH',
      }),
  },
  fleets: () => getJSON<FleetOut[]>('/api/v1/fleets'),
  fleetDevices: (fleetId: string) =>
    getJSON<DeviceOut[]>(`/api/v1/fleets/${encodeURIComponent(fleetId)}/devices`),
  deviceState: (deviceId: string) =>
    getJSON<DeviceReportedStateItemOut[]>(`/api/v1/devices/${encodeURIComponent(deviceId)}/state`),
  deviceProcedureInvocations: (deviceId: string, opts?: { limit?: number }) => {
    const params = new URLSearchParams()
    params.set('limit', String(opts?.limit ?? 100))
    return getJSON<DeviceProcedureInvocationOut[]>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/procedure-invocations?${params.toString()}`,
    )
  },
  invokeDeviceProcedure: (deviceId: string, definitionName: string, payload: DeviceProcedureInvokeIn) =>
    sendJSON<DeviceProcedureInvocationOut>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/procedures/${encodeURIComponent(definitionName)}/invoke`,
      payload,
      { method: 'POST' },
    ),
  deviceEvents: (opts?: { device_id?: string; event_type?: string; limit?: number }) => {
    const params = new URLSearchParams()
    if (opts?.device_id) params.set('device_id', opts.device_id)
    if (opts?.event_type) params.set('event_type', opts.event_type)
    params.set('limit', String(opts?.limit ?? 200))
    return getJSON<DeviceEventOut[]>(`/api/v1/device-events?${params.toString()}`)
  },
  search: (
    q: string,
    opts?: { limit?: number; offset?: number; entityTypes?: Array<OperatorSearchResultOut['entity_type']> },
  ) => {
    const params = new URLSearchParams()
    params.set('q', q)
    params.set('limit', String(opts?.limit ?? 50))
    params.set('offset', String(opts?.offset ?? 0))
    for (const entityType of opts?.entityTypes ?? []) params.append('entity_type', entityType)
    return getJSON<OperatorSearchResultOut[]>(`/api/v1/search?${params.toString()}`)
  },
  searchPage: (
    q: string,
    opts?: { limit?: number; offset?: number; entityTypes?: Array<OperatorSearchResultOut['entity_type']> },
  ) => {
    const params = new URLSearchParams()
    params.set('q', q)
    params.set('limit', String(opts?.limit ?? 50))
    params.set('offset', String(opts?.offset ?? 0))
    for (const entityType of opts?.entityTypes ?? []) params.append('entity_type', entityType)
    return getJSON<OperatorSearchPageOut>(`/api/v1/search-page?${params.toString()}`)
  },
  operatorEvents: (opts?: {
    limit?: number
    offset?: number
    device_id?: string
    sourceKinds?: Array<OperatorEventOut['source_kind']>
    event_name?: string
  }) => {
    const params = new URLSearchParams()
    params.set('limit', String(opts?.limit ?? 50))
    params.set('offset', String(opts?.offset ?? 0))
    if (opts?.device_id) params.set('device_id', opts.device_id)
    if (opts?.event_name) params.set('event_name', opts.event_name)
    for (const sourceKind of opts?.sourceKinds ?? []) params.append('source_kind', sourceKind)
    return getJSON<OperatorEventPageOut>(`/api/v1/operator-events?${params.toString()}`)
  },
  alerts: (
    opts?: {
      limit?: number
      device_id?: string
      open_only?: boolean
      severity?: string
      alert_type?: string
      q?: string
      before?: string
      before_id?: string
    },
  ) => {
    const params = new URLSearchParams()
    params.set('limit', String(opts?.limit ?? 50))
    if (opts?.device_id) params.set('device_id', opts.device_id)
    if (opts?.open_only) params.set('open_only', 'true')
    if (opts?.severity) params.set('severity', opts.severity)
    if (opts?.alert_type) params.set('alert_type', opts.alert_type)
    if (opts?.q) params.set('q', opts.q)
    if (opts?.before) params.set('before', opts.before)
    if (opts?.before_id) params.set('before_id', opts.before_id)
    return getJSON<AlertOut[]>(`/api/v1/alerts?${params.toString()}`)
  },
  telemetryContract: () => getJSON<TelemetryContract>('/api/v1/contracts/telemetry'),
  edgePolicyContract: () => getJSON<EdgePolicyContractOut>('/api/v1/contracts/edge_policy'),
  telemetry: (device_id: string, opts?: { metric?: string; since?: string; until?: string; limit?: number }) => {
    const params = new URLSearchParams()
    if (opts?.metric) params.set('metric', opts.metric)
    if (opts?.since) params.set('since', opts.since)
    if (opts?.until) params.set('until', opts.until)
    params.set('limit', String(opts?.limit ?? 200))
    return getJSON<TelemetryPoint[]>(
      `/api/v1/devices/${encodeURIComponent(device_id)}/telemetry?${params.toString()}`,
    )
  },
  timeseriesMulti: (
    device_id: string,
    metrics: string[],
    bucket: 'minute' | 'hour' = 'minute',
    opts?: { since?: string; until?: string; limit?: number },
  ) => {
    const params = new URLSearchParams()
    for (const m of metrics) params.append('metrics', m)
    params.set('bucket', bucket)
    if (opts?.since) params.set('since', opts.since)
    if (opts?.until) params.set('until', opts.until)
    if (opts?.limit) params.set('limit', String(opts.limit))
    return getJSON<TimeseriesMultiPoint[]>(
      `/api/v1/devices/${encodeURIComponent(device_id)}/timeseries_multi?${params.toString()}`,
    )
  },
  timeseries: (
    device_id: string,
    metric: string,
    bucket: 'minute' | 'hour' = 'minute',
    opts?: { since?: string; until?: string; limit?: number },
  ) => {
    const params = new URLSearchParams()
    params.set('metric', metric)
    params.set('bucket', bucket)
    if (opts?.since) params.set('since', opts.since)
    if (opts?.until) params.set('until', opts.until)
    if (opts?.limit) params.set('limit', String(opts.limit))
    return getJSON<TimeseriesPoint[]>(`/api/v1/devices/${encodeURIComponent(device_id)}/timeseries?${params.toString()}`)
  },
  latestTelemetry: (device_id: string) =>
    getJSON<TelemetryPoint[]>(
      `/api/v1/devices/${encodeURIComponent(device_id)}/telemetry?limit=1`,
    ).then((rows) => rows[0] ?? null),
  media: {
    list: (deviceId: string, opts: { token: string; limit?: number }) => {
      const params = new URLSearchParams()
      params.set('limit', String(opts.limit ?? 200))
      return getJSON<MediaObjectOut[]>(
        `/api/v1/devices/${encodeURIComponent(deviceId)}/media?${params.toString()}`,
        { headers: bearerHeaders(opts.token) },
      )
    },
    downloadPath: (mediaId: string) => `/api/v1/media/${encodeURIComponent(mediaId)}/download`,
    downloadBlob: (mediaId: string, token: string) =>
      getBlob(`/api/v1/media/${encodeURIComponent(mediaId)}/download`, {
        headers: bearerHeaders(token),
        cache: 'no-store',
      }),
  },

  admin: {
    devices: (adminKey: string) => getJSON<DeviceOut[]>('/api/v1/admin/devices', { headers: adminHeaders(adminKey) }),
    createDevice: (adminKey: string | null | undefined, payload: CreateDeviceIn) =>
      sendJSON<DeviceOut>('/api/v1/admin/devices', payload, { method: 'POST', headers: adminHeaders(adminKey) }),
    updateDevice: (adminKey: string | null | undefined, deviceId: string, payload: UpdateDeviceIn) =>
      sendJSON<DeviceOut>(`/api/v1/admin/devices/${encodeURIComponent(deviceId)}`, payload, {
        method: 'PATCH',
        headers: adminHeaders(adminKey),
      }),
    shutdownDevice: (
      adminKey: string | null | undefined,
      deviceId: string,
      payload: AdminDeviceShutdownIn,
    ) =>
      sendJSON<DeviceControlsOut>(
        `/api/v1/admin/devices/${encodeURIComponent(deviceId)}/controls/shutdown`,
        payload,
        {
          method: 'POST',
          headers: adminHeaders(adminKey),
        },
      ),
    createReleaseManifest: (
      adminKey: string | null | undefined,
      payload: ReleaseManifestCreateIn,
    ) =>
      sendJSON<ReleaseManifestOut>('/api/v1/admin/releases/manifests', payload, {
        method: 'POST',
        headers: adminHeaders(adminKey),
      }),
    updateReleaseManifest: (
      adminKey: string | null | undefined,
      manifestId: string,
      payload: ReleaseManifestUpdateIn,
    ) =>
      sendJSON<ReleaseManifestOut>(`/api/v1/admin/releases/manifests/${encodeURIComponent(manifestId)}`, payload, {
        method: 'PATCH',
        headers: adminHeaders(adminKey),
      }),
    releaseManifests: (adminKey: string, opts?: { status?: string; limit?: number }) => {
      const params = new URLSearchParams()
      if (opts?.status) params.set('status', opts.status)
      params.set('limit', String(opts?.limit ?? 200))
      return getJSON<ReleaseManifestOut[]>(`/api/v1/admin/releases/manifests?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    deployments: (
      adminKey: string,
      opts?: { status?: string; manifest_id?: string; selector_channel?: string; limit?: number },
    ) => {
      const params = new URLSearchParams()
      if (opts?.status) params.set('status', opts.status)
      if (opts?.manifest_id) params.set('manifest_id', opts.manifest_id)
      if (opts?.selector_channel) params.set('selector_channel', opts.selector_channel)
      params.set('limit', String(opts?.limit ?? 200))
      return getJSON<DeploymentOut[]>(`/api/v1/admin/deployments?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    createDeployment: (adminKey: string | null | undefined, payload: DeploymentCreateIn) =>
      sendJSON<DeploymentOut>('/api/v1/admin/deployments', payload, {
        method: 'POST',
        headers: adminHeaders(adminKey),
      }),
    deployment: (adminKey: string, deploymentId: string) =>
      getJSON<DeploymentDetailOut>(`/api/v1/admin/deployments/${encodeURIComponent(deploymentId)}`, {
        headers: adminHeaders(adminKey),
      }),
    deploymentTargets: (
      adminKey: string,
      deploymentId: string,
      opts?: { status?: string; q?: string; limit?: number; offset?: number },
    ) => {
      const params = new URLSearchParams()
      if (opts?.status) params.set('status', opts.status)
      if (opts?.q) params.set('q', opts.q)
      params.set('limit', String(opts?.limit ?? 200))
      params.set('offset', String(opts?.offset ?? 0))
      return getJSON<DeploymentTargetPageOut>(
        `/api/v1/admin/deployments/${encodeURIComponent(deploymentId)}/targets?${params.toString()}`,
        {
          headers: adminHeaders(adminKey),
        },
      )
    },
    pauseDeployment: (adminKey: string | null | undefined, deploymentId: string) =>
      sendJSON<DeploymentActionOut>(
        `/api/v1/admin/deployments/${encodeURIComponent(deploymentId)}/pause`,
        {},
        {
          method: 'POST',
          headers: adminHeaders(adminKey),
        },
      ),
    resumeDeployment: (adminKey: string | null | undefined, deploymentId: string) =>
      sendJSON<DeploymentActionOut>(
        `/api/v1/admin/deployments/${encodeURIComponent(deploymentId)}/resume`,
        {},
        {
          method: 'POST',
          headers: adminHeaders(adminKey),
        },
      ),
    abortDeployment: (adminKey: string | null | undefined, deploymentId: string, opts?: { reason?: string }) => {
      const params = new URLSearchParams()
      if (opts?.reason?.trim()) params.set('reason', opts.reason.trim())
      const qs = params.toString()
      const path = `/api/v1/admin/deployments/${encodeURIComponent(deploymentId)}/abort${qs ? `?${qs}` : ''}`
      return sendJSON<DeploymentActionOut>(path, {}, { method: 'POST', headers: adminHeaders(adminKey) })
    },
    deviceAccess: {
      list: (adminKey: string, deviceId: string) =>
        getJSON<DeviceAccessGrantOut[]>(
          `/api/v1/admin/devices/${encodeURIComponent(deviceId)}/access`,
          { headers: adminHeaders(adminKey) },
        ),
      put: (
        adminKey: string,
        deviceId: string,
        principalEmail: string,
        payload: { access_role: 'viewer' | 'operator' | 'owner' },
      ) =>
        sendJSON<DeviceAccessGrantOut>(
          `/api/v1/admin/devices/${encodeURIComponent(deviceId)}/access/${encodeURIComponent(principalEmail)}`,
          payload,
          {
            method: 'PUT',
            headers: adminHeaders(adminKey),
          },
        ),
      delete: (adminKey: string, deviceId: string, principalEmail: string) =>
        sendJSON<DeviceAccessGrantOut>(
          `/api/v1/admin/devices/${encodeURIComponent(deviceId)}/access/${encodeURIComponent(principalEmail)}`,
          {},
          {
            method: 'DELETE',
            headers: adminHeaders(adminKey),
          },
        ),
    },
    fleets: (adminKey: string) =>
      getJSON<FleetOut[]>('/api/v1/admin/fleets', { headers: adminHeaders(adminKey) }),
    createFleet: (adminKey: string | null | undefined, payload: FleetCreateIn) =>
      sendJSON<FleetOut>('/api/v1/admin/fleets', payload, {
        method: 'POST',
        headers: adminHeaders(adminKey),
      }),
    updateFleet: (adminKey: string | null | undefined, fleetId: string, payload: FleetUpdateIn) =>
      sendJSON<FleetOut>(`/api/v1/admin/fleets/${encodeURIComponent(fleetId)}`, payload, {
        method: 'PATCH',
        headers: adminHeaders(adminKey),
      }),
    addFleetDevice: (adminKey: string | null | undefined, fleetId: string, deviceId: string) =>
      sendJSON<FleetMembershipOut>(
        `/api/v1/admin/fleets/${encodeURIComponent(fleetId)}/devices/${encodeURIComponent(deviceId)}`,
        {},
        { method: 'PUT', headers: adminHeaders(adminKey) },
      ),
    removeFleetDevice: (adminKey: string | null | undefined, fleetId: string, deviceId: string) =>
      sendJSON<FleetMembershipOut>(
        `/api/v1/admin/fleets/${encodeURIComponent(fleetId)}/devices/${encodeURIComponent(deviceId)}`,
        {},
        { method: 'DELETE', headers: adminHeaders(adminKey) },
      ),
    fleetAccess: {
      list: (adminKey: string, fleetId: string) =>
        getJSON<FleetAccessGrantOut[]>(
          `/api/v1/admin/fleets/${encodeURIComponent(fleetId)}/access`,
          { headers: adminHeaders(adminKey) },
        ),
      put: (
        adminKey: string,
        fleetId: string,
        principalEmail: string,
        payload: { access_role: 'viewer' | 'operator' | 'owner' },
      ) =>
        sendJSON<FleetAccessGrantOut>(
          `/api/v1/admin/fleets/${encodeURIComponent(fleetId)}/access/${encodeURIComponent(principalEmail)}`,
          payload,
          { method: 'PUT', headers: adminHeaders(adminKey) },
        ),
      delete: (adminKey: string, fleetId: string, principalEmail: string) =>
        sendJSON<FleetAccessGrantOut>(
          `/api/v1/admin/fleets/${encodeURIComponent(fleetId)}/access/${encodeURIComponent(principalEmail)}`,
          {},
          { method: 'DELETE', headers: adminHeaders(adminKey) },
        ),
    },
    procedureDefinitions: (adminKey: string) =>
      getJSON<DeviceProcedureDefinitionOut[]>('/api/v1/admin/procedures/definitions', {
        headers: adminHeaders(adminKey),
      }),
    createProcedureDefinition: (adminKey: string | null | undefined, payload: DeviceProcedureDefinitionCreateIn) =>
      sendJSON<DeviceProcedureDefinitionOut>('/api/v1/admin/procedures/definitions', payload, {
        method: 'POST',
        headers: adminHeaders(adminKey),
      }),
    ingestions: (adminKey: string, opts?: { device_id?: string; limit?: number }) => {
      const params = new URLSearchParams()
      if (opts?.device_id) params.set('device_id', opts.device_id)
      params.set('limit', String(opts?.limit ?? 200))
      return getJSON<IngestionBatchOut[]>(`/api/v1/admin/ingestions?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    ingestionsPage: (adminKey: string, opts?: { device_id?: string; limit?: number; offset?: number }) => {
      const params = new URLSearchParams()
      if (opts?.device_id) params.set('device_id', opts.device_id)
      params.set('limit', String(opts?.limit ?? 200))
      params.set('offset', String(opts?.offset ?? 0))
      return getJSON<IngestionBatchPageOut>(`/api/v1/admin/ingestions-page?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    driftEvents: (adminKey: string, opts?: { device_id?: string; limit?: number }) => {
      const params = new URLSearchParams()
      if (opts?.device_id) params.set('device_id', opts.device_id)
      params.set('limit', String(opts?.limit ?? 200))
      return getJSON<DriftEventOut[]>(`/api/v1/admin/drift-events?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    driftEventsPage: (adminKey: string, opts?: { device_id?: string; limit?: number; offset?: number }) => {
      const params = new URLSearchParams()
      if (opts?.device_id) params.set('device_id', opts.device_id)
      params.set('limit', String(opts?.limit ?? 200))
      params.set('offset', String(opts?.offset ?? 0))
      return getJSON<DriftEventPageOut>(`/api/v1/admin/drift-events-page?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    notifications: (adminKey: string, opts?: { device_id?: string; source_kind?: string; channel?: string; decision?: string; delivered?: boolean; limit?: number }) => {
      const params = new URLSearchParams()
      if (opts?.device_id) params.set('device_id', opts.device_id)
      if (opts?.source_kind) params.set('source_kind', opts.source_kind)
      if (opts?.channel) params.set('channel', opts.channel)
      if (opts?.decision) params.set('decision', opts.decision)
      if (typeof opts?.delivered === 'boolean') params.set('delivered', String(opts.delivered))
      params.set('limit', String(opts?.limit ?? 200))
      return getJSON<NotificationEventOut[]>(`/api/v1/admin/notifications?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    notificationsPage: (
      adminKey: string,
      opts?: { device_id?: string; source_kind?: string; channel?: string; decision?: string; delivered?: boolean; limit?: number; offset?: number },
    ) => {
      const params = new URLSearchParams()
      if (opts?.device_id) params.set('device_id', opts.device_id)
      if (opts?.source_kind) params.set('source_kind', opts.source_kind)
      if (opts?.channel) params.set('channel', opts.channel)
      if (opts?.decision) params.set('decision', opts.decision)
      if (typeof opts?.delivered === 'boolean') params.set('delivered', String(opts.delivered))
      params.set('limit', String(opts?.limit ?? 200))
      params.set('offset', String(opts?.offset ?? 0))
      return getJSON<NotificationEventPageOut>(`/api/v1/admin/notifications-page?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    edgePolicyContractSource: (adminKey: string) =>
      getJSON<EdgePolicyContractSourceOut>('/api/v1/admin/contracts/edge-policy/source', {
        headers: adminHeaders(adminKey),
      }),
    updateEdgePolicyContract: (adminKey: string, payload: EdgePolicyContractUpdateIn) =>
      sendJSON<EdgePolicyContractOut>('/api/v1/admin/contracts/edge-policy', payload, {
        method: 'PATCH',
        headers: adminHeaders(adminKey),
      }),
    notificationDestinations: (adminKey: string) =>
      getJSON<NotificationDestinationOut[]>('/api/v1/admin/notification-destinations', {
        headers: adminHeaders(adminKey),
      }),
    createNotificationDestination: (
      adminKey: string,
      payload: NotificationDestinationCreateIn,
    ) =>
      sendJSON<NotificationDestinationOut>('/api/v1/admin/notification-destinations', payload, {
        method: 'POST',
        headers: adminHeaders(adminKey),
      }),
    updateNotificationDestination: (
      adminKey: string,
      destinationId: string,
      payload: NotificationDestinationUpdateIn,
    ) =>
      sendJSON<NotificationDestinationOut>(
        `/api/v1/admin/notification-destinations/${encodeURIComponent(destinationId)}`,
        payload,
        {
          method: 'PATCH',
          headers: adminHeaders(adminKey),
        },
      ),
    deleteNotificationDestination: (adminKey: string, destinationId: string) =>
      sendJSON<NotificationDestinationOut>(
        `/api/v1/admin/notification-destinations/${encodeURIComponent(destinationId)}`,
        {},
        {
          method: 'DELETE',
          headers: adminHeaders(adminKey),
        },
      ),
    events: (adminKey: string, opts?: { limit?: number; action?: string; target_type?: string; device_id?: string }) => {
      const params = new URLSearchParams()
      if (opts?.action) params.set('action', opts.action)
      if (opts?.target_type) params.set('target_type', opts.target_type)
      if (opts?.device_id) params.set('device_id', opts.device_id)
      params.set('limit', String(opts?.limit ?? 300))
      return getJSON<AdminEventOut[]>(`/api/v1/admin/events?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    eventsPage: (adminKey: string, opts?: { limit?: number; offset?: number; action?: string; target_type?: string; device_id?: string }) => {
      const params = new URLSearchParams()
      if (opts?.action) params.set('action', opts.action)
      if (opts?.target_type) params.set('target_type', opts.target_type)
      if (opts?.device_id) params.set('device_id', opts.device_id)
      params.set('limit', String(opts?.limit ?? 300))
      params.set('offset', String(opts?.offset ?? 0))
      return getJSON<AdminEventPageOut>(`/api/v1/admin/events-page?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    exports: (adminKey: string, opts?: { status?: string; limit?: number }) => {
      const params = new URLSearchParams()
      if (opts?.status) params.set('status_filter', opts.status)
      params.set('limit', String(opts?.limit ?? 200))
      return getJSON<ExportBatchOut[]>(`/api/v1/admin/exports?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
    exportsPage: (adminKey: string, opts?: { status?: string; limit?: number; offset?: number }) => {
      const params = new URLSearchParams()
      if (opts?.status) params.set('status_filter', opts.status)
      params.set('limit', String(opts?.limit ?? 200))
      params.set('offset', String(opts?.offset ?? 0))
      return getJSON<ExportBatchPageOut>(`/api/v1/admin/exports-page?${params.toString()}`, {
        headers: adminHeaders(adminKey),
      })
    },
  },
}
