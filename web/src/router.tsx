import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router'
import { AppShell, PortfolioDevtools } from './portfolio-ui'
import { DevicesPage } from './pages/Devices'
import { DeviceDetailPage } from './pages/DeviceDetail'
import { AlertsPage } from './pages/Alerts'
import { MetaPage } from './pages/Meta'

const rootRoute = createRootRoute({
  component: () => (
    <AppShell
      appName="EdgeWatch Telemetry"
      appBadge="Edge + Ops"
      nav={[
        { to: '/', label: 'Devices' },
        { to: '/alerts', label: 'Alerts' },
        { to: '/meta', label: 'Meta' },
      ]}
      docsHref="/docs"
    >
      <Outlet />
      <PortfolioDevtools />
    </AppShell>
  ),
})

const devicesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: DevicesPage,
})

const deviceDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/devices/$deviceId',
  component: DeviceDetailPage,
})

const alertsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/alerts',
  component: AlertsPage,
})

const metaRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/meta',
  component: MetaPage,
})

export const routeTree = rootRoute.addChildren([devicesRoute, deviceDetailRoute, alertsRoute, metaRoute])

export const router = createRouter({
  routeTree,
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
