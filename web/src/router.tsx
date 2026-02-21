import { createRootRoute, createRoute, createRouter } from '@tanstack/react-router'
import { RootLayout } from './RootLayout'
import { DashboardPage } from './pages/Dashboard'
import { DevicesPage } from './pages/Devices'
import { DeviceDetailPage } from './pages/DeviceDetail'
import { AlertsPage } from './pages/Alerts'
import { ContractsPage } from './pages/Contracts'
import { AdminPage } from './pages/Admin'
import { SettingsPage } from './pages/Settings'
import { MetaPage } from './pages/Meta'
import { ErrorPage } from './pages/Error'
import { NotFoundPage } from './pages/NotFound'

const rootRoute = createRootRoute({
  component: RootLayout,
  errorComponent: ({ error }) => <ErrorPage error={error} />,
  notFoundComponent: () => <NotFoundPage />,
})

const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: DashboardPage,
})

const devicesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/devices',
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

const contractsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/contracts',
  component: ContractsPage,
})

const adminRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/admin',
  component: AdminPage,
})

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: SettingsPage,
})

const metaRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/meta',
  component: MetaPage,
})

export const routeTree = rootRoute.addChildren([
  dashboardRoute,
  devicesRoute,
  deviceDetailRoute,
  alertsRoute,
  contractsRoute,
  adminRoute,
  settingsRoute,
  metaRoute,
])

export const router = createRouter({
  routeTree,
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
