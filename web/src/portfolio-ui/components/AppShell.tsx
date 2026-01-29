import * as React from 'react'
import { Link } from '@tanstack/react-router'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import { cn } from '../lib/utils'
import { Separator } from '../ui/separator'

export type NavItem = {
  to: string
  label: string
}

export type AppShellProps = {
  appName: string
  appBadge?: string
  nav: NavItem[]
  docsHref?: string
  repoHref?: string
  children: React.ReactNode
}

function getInitialTheme(): 'light' | 'dark' {
  try {
    const stored = localStorage.getItem('theme')
    return stored === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function AppShell(props: AppShellProps) {
  const [theme, setTheme] = React.useState<'light' | 'dark'>(() => getInitialTheme())

  React.useEffect(() => {
    const root = document.documentElement
    if (theme === 'dark') root.classList.add('dark')
    else root.classList.remove('dark')
    try {
      localStorage.setItem('theme', theme)
    } catch {}
  }, [theme])

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold tracking-tight">{props.appName}</span>
            {props.appBadge ? <Badge variant="secondary">{props.appBadge}</Badge> : null}
          </div>

          <nav className="flex items-center gap-1">
            {props.nav.map((item) => (
              <Link
                key={item.to}
                to={item.to as any}
                className={cn(
                  'rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                )}
                activeProps={{
                  className:
                    'rounded-md px-3 py-1.5 text-sm bg-accent text-accent-foreground',
                }}
              >
                {item.label}
              </Link>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            {props.docsHref ? (
              <a
                href={props.docsHref}
                className="text-sm text-muted-foreground hover:text-foreground"
                target="_blank"
                rel="noreferrer"
              >
                API Docs
              </a>
            ) : null}
            {props.repoHref ? (
              <>
                <Separator className="h-5 w-px bg-border" />
                <a
                  href={props.repoHref}
                  className="text-sm text-muted-foreground hover:text-foreground"
                  target="_blank"
                  rel="noreferrer"
                >
                  Repo
                </a>
              </>
            ) : null}
            <Separator className="h-5 w-px bg-border" />
            <Button
              variant="outline"
              size="sm"
              onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
              aria-label="Toggle theme"
              title="Toggle theme"
            >
              {theme === 'dark' ? 'Light' : 'Dark'}
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">{props.children}</main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 text-xs text-muted-foreground">
          <span>Portfolio demo UI • shadcn + Tailwind + TanStack</span>
          <span>Local-first friendly • GCP deployable</span>
        </div>
      </footer>
    </div>
  )
}
