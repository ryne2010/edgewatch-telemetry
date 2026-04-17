import { createRootRoute, createRoute, createRouter, lazyRouteComponent } from '@tanstack/react-router'
import { RootLayout } from './RootLayout'
import { ErrorPage } from './pages/Error'
import { NotFoundPage } from './pages/NotFound'

const DashboardPage = lazyRouteComponent(() => import('./pages/Dashboard'), 'DashboardPage')
const DevicesPage = lazyRouteComponent(() => import('./pages/Devices'), 'DevicesPage')
const DeviceDetailPage = lazyRouteComponent(() => import('./pages/DeviceDetail'), 'DeviceDetailPage')
const AlertsPage = lazyRouteComponent(() => import('./pages/Alerts'), 'AlertsPage')
const AdminPage = lazyRouteComponent(() => import('./pages/Admin'), 'AdminPage')
const CellularPage = lazyRouteComponent(() => import('./pages/Cellular'), 'CellularPage')
const FleetsPage = lazyRouteComponent(() => import('./pages/Fleets'), 'FleetsPage')
const LivePage = lazyRouteComponent(() => import('./pages/Live'), 'LivePage')
const ReleasesPage = lazyRouteComponent(() => import('./pages/Releases'), 'ReleasesPage')
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
  validateSearch: (search: Record<string, unknown>) => ({
    tab: typeof search.tab === 'string' ? search.tab : '',
    deviceId: typeof search.deviceId === 'string' ? search.deviceId : '',
    batchId: typeof search.batchId === 'string' ? search.batchId : '',
    accessDeviceId: typeof search.accessDeviceId === 'string' ? search.accessDeviceId : '',
    fleetId: typeof search.fleetId === 'string' ? search.fleetId : '',
    status: typeof search.status === 'string' ? search.status : '',
    exportId: typeof search.exportId === 'string' ? search.exportId : '',
    action: typeof search.action === 'string' ? search.action : '',
    targetType: typeof search.targetType === 'string' ? search.targetType : '',
    sourceKind: typeof search.sourceKind === 'string' ? search.sourceKind : '',
    channel: typeof search.channel === 'string' ? search.channel : '',
    decision: typeof search.decision === 'string' ? search.decision : '',
    delivered: typeof search.delivered === 'string' ? search.delivered : '',
    procedureName: typeof search.procedureName === 'string' ? search.procedureName : '',
  }),
  component: AdminPage,
})

const cellularRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/cellular',
  component: CellularPage,
})

const fleetsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/fleets',
  validateSearch: (search: Record<string, unknown>) => ({
    fleetId: typeof search.fleetId === 'string' ? search.fleetId : '',
  }),
  component: FleetsPage,
})

const liveRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/live',
  validateSearch: (search: Record<string, unknown>) => ({
    deviceId: typeof search.deviceId === 'string' ? search.deviceId : '',
    sourceKinds: typeof search.sourceKinds === 'string' ? search.sourceKinds : '',
    eventName: typeof search.eventName === 'string' ? search.eventName : '',
    sinceSeconds: typeof search.sinceSeconds === 'string' ? search.sinceSeconds : '',
  }),
  component: LivePage,
})

const releasesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/releases',
  validateSearch: (search: Record<string, unknown>) => ({
    deploymentId: typeof search.deploymentId === 'string' ? search.deploymentId : '',
    manifestId: typeof search.manifestId === 'string' ? search.manifestId : '',
    targetDeviceId: typeof search.targetDeviceId === 'string' ? search.targetDeviceId : '',
  }),
  component: ReleasesPage,
})

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  validateSearch: (search: Record<string, unknown>) => ({
    destinationId: typeof search.destinationId === 'string' ? search.destinationId : '',
  }),
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
  cellularRoute,
  fleetsRoute,
  liveRoute,
  releasesRoute,
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
