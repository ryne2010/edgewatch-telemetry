export type DeviceStatusFilter = 'all' | 'online' | 'offline' | 'unknown' | 'sleep' | 'disabled'

export type DeviceHealthFilter =
  | 'all'
  | 'open_alerts'
  | 'water_pressure_low'
  | 'battery_low'
  | 'weak_signal'
  | 'oil_pressure_low'
  | 'oil_level_low'
  | 'drip_oil_low'
  | 'oil_life_low'
  | 'no_telemetry'

export type DevicesSearchState = {
  filterText: string
  statusFilter: DeviceStatusFilter
  openAlertsOnly: boolean
  healthFilter: DeviceHealthFilter
}

export type SeverityFilter = 'all' | 'critical' | 'warning' | 'info'
export type ResolutionFilter = 'all' | 'open' | 'resolved'

export type AlertsSearchState = {
  resolutionFilter: ResolutionFilter
  severityFilter: SeverityFilter
  typeFilter: string
  deviceFilter: string
  search: string
  limit: number
}

export type TimelineWindowHours = 24 | 72 | 168 | 336

export type DashboardSearchState = {
  timelineWindowHours: TimelineWindowHours
  timelineOpenOnly: boolean
  timelineSeverity: SeverityFilter
  timelineSelectedDayKey: 'all' | string
  timelineExpanded: boolean
}

function stripLeadingQuestionMark(searchStr: string): string {
  return searchStr.startsWith('?') ? searchStr.slice(1) : searchStr
}

function readFirst(params: URLSearchParams, keys: readonly string[]): string {
  for (const key of keys) {
    const value = params.get(key)
    if (value != null) return value
  }
  return ''
}

function readBoolean(params: URLSearchParams, keys: readonly string[]): boolean {
  const raw = readFirst(params, keys).toLowerCase()
  return raw === '1' || raw === 'true' || raw === 'yes' || raw === 'on'
}

function parseLimit(raw: string, fallback: number): number {
  const parsed = Number.parseInt(raw, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

export function normalizeSearchString(searchStr: string): string {
  return stripLeadingQuestionMark(searchStr)
}

export function buildHref(pathname: string, search: string): string {
  return search ? `${pathname}?${search}` : pathname
}

export function parseDevicesSearch(searchStr: string): DevicesSearchState {
  const params = new URLSearchParams(stripLeadingQuestionMark(searchStr))

  const rawStatus = readFirst(params, ['status', 'deviceStatus']).toLowerCase()
  const statusFilter: DeviceStatusFilter =
    rawStatus === 'online' ||
    rawStatus === 'offline' ||
    rawStatus === 'unknown' ||
    rawStatus === 'sleep' ||
    rawStatus === 'disabled'
      ? rawStatus
      : 'all'

  const rawHealth = readFirst(params, ['health', 'focus']).toLowerCase()
  const healthFilter: DeviceHealthFilter =
    rawHealth === 'open_alerts' ||
    rawHealth === 'water_pressure_low' ||
    rawHealth === 'battery_low' ||
    rawHealth === 'weak_signal' ||
    rawHealth === 'oil_pressure_low' ||
    rawHealth === 'oil_level_low' ||
    rawHealth === 'drip_oil_low' ||
    rawHealth === 'oil_life_low' ||
    rawHealth === 'no_telemetry'
      ? rawHealth
      : 'all'

  return {
    filterText: readFirst(params, ['q', 'search']).trim(),
    statusFilter,
    openAlertsOnly: readBoolean(params, ['openAlertsOnly', 'open_alerts_only']),
    healthFilter,
  }
}

export function buildDevicesSearch(state: DevicesSearchState): string {
  const params = new URLSearchParams()
  if (state.filterText.trim()) params.set('q', state.filterText.trim())
  if (state.statusFilter !== 'all') params.set('status', state.statusFilter)
  if (state.openAlertsOnly) params.set('openAlertsOnly', 'true')
  if (state.healthFilter !== 'all') params.set('health', state.healthFilter)
  return params.toString()
}

export function parseAlertsSearch(searchStr: string): AlertsSearchState {
  const params = new URLSearchParams(stripLeadingQuestionMark(searchStr))

  const rawSeverity = readFirst(params, ['severity']).toLowerCase()
  const severityFilter: SeverityFilter =
    rawSeverity === 'critical' || rawSeverity === 'warning' || rawSeverity === 'info' ? rawSeverity : 'all'

  const rawResolution = readFirst(params, ['resolution']).toLowerCase()
  let resolutionFilter: ResolutionFilter = 'all'
  if (rawResolution === 'open' || rawResolution === 'resolved' || rawResolution === 'all') {
    resolutionFilter = rawResolution
  } else if (readBoolean(params, ['resolvedOnly', 'resolved_only'])) {
    resolutionFilter = 'resolved'
  } else if (readBoolean(params, ['openOnly', 'open_only'])) {
    resolutionFilter = 'open'
  }

  return {
    resolutionFilter,
    severityFilter,
    typeFilter: readFirst(params, ['type', 'alertType', 'alert_type']).trim() || 'all',
    deviceFilter: readFirst(params, ['device', 'device_id']).trim(),
    search: readFirst(params, ['q', 'search']).trim(),
    limit: parseLimit(readFirst(params, ['limit', 'pageSize']), 200),
  }
}

export function buildAlertsSearch(state: AlertsSearchState): string {
  const params = new URLSearchParams()
  if (state.resolutionFilter !== 'all') params.set('resolution', state.resolutionFilter)
  if (state.severityFilter !== 'all') params.set('severity', state.severityFilter)
  if (state.typeFilter.trim() && state.typeFilter !== 'all') params.set('type', state.typeFilter.trim())
  if (state.deviceFilter.trim()) params.set('device', state.deviceFilter.trim())
  if (state.search.trim()) params.set('q', state.search.trim())
  if (state.limit !== 200) params.set('limit', String(state.limit))
  return params.toString()
}

export function parseDashboardSearch(searchStr: string): DashboardSearchState {
  const params = new URLSearchParams(stripLeadingQuestionMark(searchStr))
  const rawWindow = Number.parseInt(readFirst(params, ['timelineWindow']), 10)
  const timelineWindowHours: TimelineWindowHours =
    rawWindow === 24 || rawWindow === 72 || rawWindow === 168 || rawWindow === 336 ? rawWindow : 168

  const rawSeverity = readFirst(params, ['timelineSeverity']).toLowerCase()
  const timelineSeverity: SeverityFilter =
    rawSeverity === 'critical' || rawSeverity === 'warning' || rawSeverity === 'info' ? rawSeverity : 'all'

  const rawScope = readFirst(params, ['timelineScope']).toLowerCase()
  const timelineOpenOnly = rawScope === 'all' ? false : true

  return {
    timelineWindowHours,
    timelineOpenOnly,
    timelineSeverity,
    timelineSelectedDayKey: readFirst(params, ['timelineDay']).trim() || 'all',
    timelineExpanded: readBoolean(params, ['timelineExpanded']),
  }
}

export function buildDashboardSearch(state: DashboardSearchState): string {
  const params = new URLSearchParams()
  if (state.timelineWindowHours !== 168) params.set('timelineWindow', String(state.timelineWindowHours))
  if (!state.timelineOpenOnly) params.set('timelineScope', 'all')
  if (state.timelineSeverity !== 'all') params.set('timelineSeverity', state.timelineSeverity)
  if (state.timelineSelectedDayKey !== 'all') params.set('timelineDay', state.timelineSelectedDayKey)
  if (state.timelineExpanded) params.set('timelineExpanded', 'true')
  return params.toString()
}
