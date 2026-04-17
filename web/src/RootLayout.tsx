import React from 'react'
import { Outlet } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { useAppSettings } from './app/settings'
import { useAdminAccess } from './hooks/useAdminAccess'
import {
  AppDevtools,
  AppShell,
  IconBell,
  IconDashboard,
  IconDevices,
  IconFile,
  IconInfo,
  IconLayers,
  IconPulse,
  IconSignal,
  IconSettings,
  IconShield,
} from './ui-kit'

export function RootLayout() {
  const { adminKey } = useAppSettings()
  const health = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })

  // Prefer backend-reported environment (dev/stage/prod). Fall back to Vite mode.
  const badge = health.data?.env ?? import.meta.env.MODE

  const adminEnabled = Boolean(health.data?.features?.admin?.enabled)
  const adminAuthMode = health.data?.features?.admin?.auth_mode
  const docsEnabled = Boolean(health.data?.features?.docs?.enabled)
  const { adminAccess } = useAdminAccess({
    adminEnabled,
    adminAuthMode,
    adminKey,
  })

  return (
    <AppShell
      appName="EdgeWatch Telemetry"
      appBadge={badge}
      adminEnabled={adminEnabled}
      adminAuthMode={adminAuthMode}
      adminActive={adminAccess}
      nav={[
        { to: '/', label: 'Dashboard', icon: <IconDashboard /> },
        { to: '/devices', label: 'Devices', icon: <IconDevices /> },
        { to: '/cellular', label: 'Cellular', icon: <IconSignal /> },
        { to: '/fleets', label: 'Fleets', icon: <IconLayers /> },
        { to: '/alerts', label: 'Alerts', icon: <IconBell /> },
        { to: '/live', label: 'Live', icon: <IconPulse /> },
        { to: '/releases', label: 'Releases', icon: <IconFile />, requiresAdminRoutes: true },
        { to: '/admin', label: 'Admin', icon: <IconShield />, requiresAdminRoutes: true },
        { to: '/settings', label: 'Settings', icon: <IconSettings /> },
        { to: '/meta', label: 'System', icon: <IconInfo /> },
      ]}
      docsHref={docsEnabled ? '/docs' : undefined}
    >
      <Outlet />
      <AppDevtools />
    </AppShell>
  )
}
