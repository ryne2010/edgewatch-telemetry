import * as React from 'react'
import { Link } from '@tanstack/react-router'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import { cn } from '../lib/utils'
import { useAppSettings } from '../../app/settings'

export type NavItem = {
  to: string
  label: string
  icon?: React.ReactNode
  badge?: string
  /** Hide unless the backend reports that admin routes are enabled. */
  requiresAdminRoutes?: boolean
}

export type AppShellProps = {
  appName: string
  appBadge?: string
  nav: NavItem[]
  docsHref?: string
  repoHref?: string

  /** From /api/v1/health: features.admin.enabled */
  adminEnabled?: boolean
  /** From /api/v1/health: features.admin.auth_mode (key|none) */
  adminAuthMode?: string

  children: React.ReactNode
}

function IconMenu(props: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn('h-5 w-5', props.className)} aria-hidden="true">
      <path
        fill="currentColor"
        d="M4 6.5A1.5 1.5 0 0 1 5.5 5h13A1.5 1.5 0 0 1 20 6.5 1.5 1.5 0 0 1 18.5 8h-13A1.5 1.5 0 0 1 4 6.5Zm0 5A1.5 1.5 0 0 1 5.5 10h13A1.5 1.5 0 0 1 20 11.5 1.5 1.5 0 0 1 18.5 13h-13A1.5 1.5 0 0 1 4 11.5Zm0 5A1.5 1.5 0 0 1 5.5 15h13A1.5 1.5 0 0 1 20 16.5 1.5 1.5 0 0 1 18.5 18h-13A1.5 1.5 0 0 1 4 16.5Z"
      />
    </svg>
  )
}

function IconClose(props: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn('h-5 w-5', props.className)} aria-hidden="true">
      <path
        fill="currentColor"
        d="M18.3 5.71a1 1 0 0 0-1.41 0L12 10.59 7.11 5.7A1 1 0 0 0 5.7 7.11L10.59 12l-4.88 4.89a1 1 0 1 0 1.41 1.41L12 13.41l4.89 4.88a1 1 0 0 0 1.41-1.41L13.41 12l4.88-4.89a1 1 0 0 0 0-1.4Z"
      />
    </svg>
  )
}

function ShellNavLink(props: { item: NavItem; onNavigate?: () => void }) {
  return (
    <Link
      to={props.item.to as any}
      activeOptions={{ exact: props.item.to === '/' }}
      onClick={() => props.onNavigate?.()}
      className={cn(
        'group flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground',
        'hover:bg-accent hover:text-accent-foreground',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
      )}
      activeProps={{
        className:
          'group flex items-center gap-3 rounded-md px-3 py-2 text-sm bg-accent text-accent-foreground',
      }}
    >
      {props.item.icon ? (
        <span className="inline-flex h-5 w-5 items-center justify-center text-muted-foreground group-hover:text-accent-foreground">
          {props.item.icon}
        </span>
      ) : (
        <span className="inline-flex h-5 w-5" />
      )}
      <span className="flex-1">{props.item.label}</span>
      {props.item.badge ? <Badge variant="secondary">{props.item.badge}</Badge> : null}
    </Link>
  )
}

export function AppShell(props: AppShellProps) {
  const { theme, setTheme, adminKey } = useAppSettings()
  const [mobileOpen, setMobileOpen] = React.useState(false)

  const nav = React.useMemo(() => {
    const adminEnabled = Boolean(props.adminEnabled)
    return props.nav.filter((n) => !n.requiresAdminRoutes || adminEnabled)
  }, [props.nav, props.adminEnabled])

  const adminBadge = React.useMemo(() => {
    if (!props.adminEnabled) return null
    const mode = String(props.adminAuthMode ?? 'key').toLowerCase()
    if (mode === 'none') return 'Admin (IAM)'
    return adminKey ? 'Admin' : null
  }, [props.adminEnabled, props.adminAuthMode, adminKey])

  return (
    <div className="min-h-screen bg-background text-foreground">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:border focus:bg-background focus:px-3 focus:py-2"
      >
        Skip to content
      </a>

      <div className="flex min-h-screen">
        {/* Desktop sidebar */}
        <aside className="hidden w-64 flex-col border-r bg-card lg:flex">
          <div className="flex items-center gap-2 px-4 py-4">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold tracking-tight">{props.appName}</div>
              <div className="mt-1 flex items-center gap-2">
                {props.appBadge ? <Badge variant="secondary">{props.appBadge}</Badge> : null}
                {adminBadge ? <Badge variant="outline">{adminBadge}</Badge> : null}
              </div>
            </div>
          </div>

          <nav className="flex-1 space-y-1 px-2 pb-4">
            {nav.map((item) => (
              <ShellNavLink key={item.to} item={item} />
            ))}
          </nav>

          <div className="border-t p-4">
            <div className="flex items-center justify-between gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                aria-label="Toggle theme"
                title="Toggle theme"
              >
                {theme === 'dark' ? 'Light' : 'Dark'}
              </Button>
              <div className="flex items-center gap-2">
                {props.docsHref ? (
                  <a
                    href={props.docsHref}
                    className="text-xs text-muted-foreground hover:text-foreground"
                    target="_blank"
                    rel="noreferrer"
                  >
                    API Docs
                  </a>
                ) : null}
                {props.repoHref ? (
                  <a
                    href={props.repoHref}
                    className="text-xs text-muted-foreground hover:text-foreground"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Repo
                  </a>
                ) : null}
              </div>
            </div>
            <div className="mt-3 text-xs text-muted-foreground">
              EdgeWatch • Fleet telemetry dashboard
            </div>
          </div>
        </aside>

        {/* Main column */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* Mobile header */}
          <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur lg:hidden">
            <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setMobileOpen(true)}
                aria-label="Open navigation"
                title="Open navigation"
              >
                <IconMenu />
              </Button>

              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold tracking-tight">{props.appName}</div>
                <div className="mt-1 flex items-center gap-2">
                  {props.appBadge ? <Badge variant="secondary">{props.appBadge}</Badge> : null}
                  {adminBadge ? <Badge variant="outline">{adminBadge}</Badge> : null}
                </div>
              </div>

              <Button
                variant="outline"
                size="sm"
                onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                aria-label="Toggle theme"
                title="Toggle theme"
              >
                {theme === 'dark' ? 'Light' : 'Dark'}
              </Button>
            </div>
          </header>

          {/* Mobile overlay nav */}
          {mobileOpen ? (
            <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true">
              <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
              <div className="absolute inset-y-0 left-0 w-80 max-w-[85vw] border-r bg-card shadow-xl">
                <div className="flex items-center justify-between gap-2 px-4 py-4">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold tracking-tight">{props.appName}</div>
                    <div className="mt-1 flex items-center gap-2">
                      {props.appBadge ? <Badge variant="secondary">{props.appBadge}</Badge> : null}
                      {adminBadge ? <Badge variant="outline">{adminBadge}</Badge> : null}
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setMobileOpen(false)}
                    aria-label="Close navigation"
                    title="Close navigation"
                  >
                    <IconClose />
                  </Button>
                </div>

                <nav className="space-y-1 px-2 pb-4">
                  {nav.map((item) => (
                    <ShellNavLink key={item.to} item={item} onNavigate={() => setMobileOpen(false)} />
                  ))}
                </nav>

                <div className="border-t p-4">
                  <div className="flex items-center justify-between gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                    >
                      {theme === 'dark' ? 'Light' : 'Dark'}
                    </Button>
                    <div className="flex items-center gap-2">
                      {props.docsHref ? (
                        <a
                          href={props.docsHref}
                          className="text-xs text-muted-foreground hover:text-foreground"
                          target="_blank"
                          rel="noreferrer"
                        >
                          API Docs
                        </a>
                      ) : null}
                      {props.repoHref ? (
                        <a
                          href={props.repoHref}
                          className="text-xs text-muted-foreground hover:text-foreground"
                          target="_blank"
                          rel="noreferrer"
                        >
                          Repo
                        </a>
                      ) : null}
                    </div>
                  </div>
                  <div className="mt-3 text-xs text-muted-foreground">EdgeWatch • Fleet telemetry dashboard</div>
                </div>
              </div>
            </div>
          ) : null}

          <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
            {props.children}
          </main>

          <footer className="border-t">
            <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-4 text-xs text-muted-foreground">
              <span>EdgeWatch Telemetry</span>
              <span className="hidden sm:inline">Local-first • Cloud Run + RPi ready</span>
            </div>
          </footer>
        </div>
      </div>
    </div>
  )
}
