import { createRootRoute, createRoute, createRouter, lazyRouteComponent } from '@tanstack/react-router'
import { RootLayout } from './RootLayout'
import { ErrorPage } from './pages/Error'
import { NotFoundPage } from './pages/NotFound'

const DashboardPage = lazyRouteComponent(() => import('./pages/Dashboard'), 'DashboardPage')
const DevicesPage = lazyRouteComponent(() => import('./pages/Devices'), 'DevicesPage')
const DeviceDetailPage = lazyRouteComponent(() => import('./pages/DeviceDetail'), 'DeviceDetailPage')
const AlertsPage = lazyRouteComponent(() => import('./pages/Alerts'), 'AlertsPage')
const AdminPage = lazyRouteComponent(() => import('./pages/Admin'), 'AdminPage')
const SettingsPage = lazyRouteComponent(() => import('./pages/Settings'), 'SettingsPage')
const MetaPage = lazyRouteComponent(() => import('./pages/Meta'), 'MetaPage')

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
