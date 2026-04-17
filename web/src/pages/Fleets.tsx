import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link, useSearch } from '@tanstack/react-router'
import { api, type DeviceOut, type FleetOut } from '../api'
import { useAppSettings } from '../app/settings'
import { useAdminAccess } from '../hooks/useAdminAccess'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Input, Label, Page, useToast } from '../ui-kit'
import { fmtDateTime } from '../utils/format'
import { adminAccessHint } from '../utils/adminAuth'

function statusVariant(
  status: 'online' | 'offline' | 'unknown' | 'sleep' | 'disabled',
): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (status === 'online') return 'success'
  if (status === 'offline') return 'destructive'
  if (status === 'sleep') return 'warning'
  return 'secondary'
}

export function FleetsPage() {
  const routeSearch = useSearch({ from: '/fleets' })
  const { adminKey } = useAppSettings()
  const { toast } = useToast()
  const qc = useQueryClient()
  const [selectedFleetId, setSelectedFleetId] = React.useState('')
  const [filterText, setFilterText] = React.useState('')
  const [defaultChannelInput, setDefaultChannelInput] = React.useState('stable')

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

  const fleetsQ = useQuery({
    queryKey: ['fleets'],
    queryFn: () => api.fleets(),
    staleTime: 30_000,
  })

  React.useEffect(() => {
    if (routeSearch.fleetId?.trim()) {
      setSelectedFleetId(routeSearch.fleetId.trim())
      return
    }
    if (selectedFleetId.trim()) return
    const first = fleetsQ.data?.[0]
    if (first) setSelectedFleetId(first.id)
  }, [fleetsQ.data, routeSearch.fleetId, selectedFleetId])

  const selectedFleet = React.useMemo(
    () => (fleetsQ.data ?? []).find((fleet) => fleet.id === selectedFleetId) ?? null,
    [fleetsQ.data, selectedFleetId],
  )

  React.useEffect(() => {
    if (!selectedFleet) return
    setDefaultChannelInput(selectedFleet.default_ota_channel || 'stable')
  }, [selectedFleet?.default_ota_channel, selectedFleet?.id])

  const fleetDevicesQ = useQuery({
    queryKey: ['fleetDevices', selectedFleetId],
    queryFn: () => api.fleetDevices(selectedFleetId),
    enabled: Boolean(selectedFleetId.trim()),
    staleTime: 15_000,
  })

  const updateFleetChannelMutation = useMutation({
    mutationFn: async () => {
      if (!adminAccess) throw new Error('Admin access is required to edit fleet channel defaults.')
      const default_ota_channel = defaultChannelInput.trim()
      if (!selectedFleetId.trim()) throw new Error('Select a fleet first.')
      if (!default_ota_channel) throw new Error('Default OTA channel is required.')
      return api.admin.updateFleet(adminCred, selectedFleetId, { default_ota_channel })
    },
    onSuccess: (fleet) => {
      qc.invalidateQueries({ queryKey: ['fleets'] })
      qc.invalidateQueries({ queryKey: ['admin', 'fleets'] })
      toast({
        title: 'Fleet default channel updated',
        description: `${fleet.name} now defaults to ${fleet.default_ota_channel}.`,
        variant: 'success',
      })
    },
    onError: (error) => {
      toast({
        title: 'Unable to update fleet default channel',
        description: (error as Error).message,
        variant: 'error',
      })
    },
  })

  const applyFleetChannelMutation = useMutation({
    mutationFn: async () => {
      if (!adminAccess) throw new Error('Admin access is required to push fleet channel posture.')
      const ota_channel = defaultChannelInput.trim()
      const fleetId = selectedFleetId.trim()
      if (!fleetId) throw new Error('Select a fleet first.')
      if (!ota_channel) throw new Error('Default OTA channel is required.')
      const rows = fleetDevicesQ.data ?? []
      if (!rows.length) throw new Error('No devices in the selected fleet.')
      for (const row of rows) {
        await api.admin.updateDevice(adminCred, row.device_id, { ota_channel })
      }
      return { count: rows.length, ota_channel }
    },
    onSuccess: ({ count, ota_channel }) => {
      qc.invalidateQueries({ queryKey: ['fleetDevices', selectedFleetId] })
      qc.invalidateQueries({ queryKey: ['devices'] })
      qc.invalidateQueries({ queryKey: ['devicesSummary'] })
      toast({
        title: 'Fleet channel applied',
        description: `${count} device${count === 1 ? '' : 's'} set to ${ota_channel}.`,
        variant: 'success',
      })
    },
    onError: (error) => {
      toast({
        title: 'Unable to apply fleet channel',
        description: (error as Error).message,
        variant: 'error',
      })
    },
  })

  const fleetCols = React.useMemo<ColumnDef<FleetOut>[]>(() => {
    return [
      { header: 'Name', accessorKey: 'name' },
      { header: 'Fleet ID', accessorKey: 'id', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Channel', accessorKey: 'default_ota_channel', cell: (i) => <Badge variant="secondary">{String(i.getValue())}</Badge> },
      { header: 'Devices', accessorKey: 'device_count', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      { header: 'Updated', accessorKey: 'updated_at', cell: (i) => <span className="text-muted-foreground">{fmtDateTime(i.getValue() as any)}</span> },
    ]
  }, [])

  const deviceCols = React.useMemo<ColumnDef<DeviceOut>[]>(() => {
    return [
      { header: 'Device', accessorKey: 'device_id', cell: (i) => <span className="font-mono text-xs">{String(i.getValue())}</span> },
      {
        header: 'Open',
        cell: (i) => (
          <Link to="/devices/$deviceId" params={{ deviceId: i.row.original.device_id }} className="underline text-xs">
            device
          </Link>
        ),
      },
      { header: 'Name', accessorKey: 'display_name' },
      { header: 'Status', accessorKey: 'status', cell: (i) => <Badge variant={statusVariant(i.getValue() as DeviceOut['status'])}>{String(i.getValue())}</Badge> },
      { header: 'Channel', accessorKey: 'ota_channel', cell: (i) => <Badge variant="outline">{String(i.getValue())}</Badge> },
      { header: 'Ready for OTA', cell: (i) => (i.row.original.ota_updates_enabled ? <Badge variant="success">yes</Badge> : <Badge variant="warning">no</Badge>) },
      { header: 'Busy', accessorKey: 'ota_busy_reason', cell: (i) => <span className="text-muted-foreground">{String(i.getValue() ?? '—')}</span> },
    ]
  }, [])

  const filteredDevices = React.useMemo(() => {
    const q = filterText.trim().toLowerCase()
    const rows = fleetDevicesQ.data ?? []
    if (!q) return rows
    return rows.filter((row) => row.device_id.toLowerCase().includes(q) || row.display_name.toLowerCase().includes(q))
  }, [fleetDevicesQ.data, filterText])

  return (
    <Page
      title="Fleets"
      description="Governance and release scope across accessible fleets."
      actions={
        <div className="flex items-center gap-2">
          <Badge variant="outline">fleets: {fleetsQ.data?.length ?? 0}</Badge>
          <Badge variant="secondary">devices: {fleetDevicesQ.data?.length ?? 0}</Badge>
          {selectedFleetId ? <Badge variant="secondary">{selectedFleetId}</Badge> : null}
        </div>
      }
    >
      <div className="grid gap-6 lg:grid-cols-[1.15fr_1.85fr]">
        <Card>
          <CardHeader>
            <CardTitle>Fleet list</CardTitle>
            <CardDescription>Click a row to inspect the devices in that fleet.</CardDescription>
          </CardHeader>
          <CardContent>
            {fleetsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
            {fleetsQ.isError ? <div className="text-sm text-destructive">Error: {(fleetsQ.error as Error).message}</div> : null}
            <DataTable<FleetOut>
              data={fleetsQ.data ?? []}
              columns={fleetCols}
              onRowClick={(row) => setSelectedFleetId(row.id)}
              emptyState="No accessible fleets."
            />
          </CardContent>
        </Card>

        <Card id="fleet-devices">
          <CardHeader>
            <CardTitle>Fleet devices</CardTitle>
            <CardDescription>Device membership, OTA channel, and readiness posture for the selected fleet.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {selectedFleet ? (
              <div className="grid gap-3 rounded-lg border bg-muted/20 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">{selectedFleet.name}</Badge>
                  <Badge variant="outline">default channel: {selectedFleet.default_ota_channel}</Badge>
                  <Badge variant="secondary">devices: {selectedFleet.device_count}</Badge>
                </div>
                <div className="text-sm text-muted-foreground">
                  Fleet defaults govern new membership. Apply channel posture to existing devices when you want the current fleet to align immediately.
                </div>
                {adminAccess ? (
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-end">
                    <div className="space-y-1">
                      <Label>Fleet default OTA channel</Label>
                      <Input
                        value={defaultChannelInput}
                        onChange={(e) => setDefaultChannelInput(e.target.value)}
                        placeholder="stable"
                        disabled={updateFleetChannelMutation.isPending || applyFleetChannelMutation.isPending}
                      />
                    </div>
                    <Button
                      variant="outline"
                      onClick={() => updateFleetChannelMutation.mutate()}
                      disabled={updateFleetChannelMutation.isPending || applyFleetChannelMutation.isPending || !selectedFleetId}
                    >
                      {updateFleetChannelMutation.isPending ? 'Saving default…' : 'Save default'}
                    </Button>
                    <Button
                      variant="outline"
                      onClick={() => applyFleetChannelMutation.mutate()}
                      disabled={updateFleetChannelMutation.isPending || applyFleetChannelMutation.isPending || !selectedFleetId}
                    >
                      {applyFleetChannelMutation.isPending ? 'Applying channel…' : 'Apply to fleet devices'}
                    </Button>
                  </div>
                ) : adminEnabled ? (
                  <div className="text-xs text-muted-foreground">
                    {adminAccessHint(new Error('Admin access required'), adminAuthMode) ?? 'Admin access required for fleet governance changes.'}
                  </div>
                ) : null}
              </div>
            ) : null}
            <div className="flex gap-2">
              <Input value={filterText} onChange={(e) => setFilterText(e.target.value)} placeholder="Filter devices in this fleet…" />
              <Button variant="outline" onClick={() => setFilterText('')}>Clear</Button>
            </div>
            {fleetDevicesQ.isLoading ? <div className="text-sm text-muted-foreground">Loading devices…</div> : null}
            {fleetDevicesQ.isError ? <div className="text-sm text-destructive">Error: {(fleetDevicesQ.error as Error).message}</div> : null}
            <DataTable<DeviceOut>
              data={filteredDevices}
              columns={deviceCols}
              emptyState={selectedFleetId ? 'No devices in this fleet.' : 'Select a fleet to view devices.'}
            />
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}
