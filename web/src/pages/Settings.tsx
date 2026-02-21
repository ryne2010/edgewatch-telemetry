import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api } from '../api'
import { useAppSettings } from '../app/settings'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label, Page, useToast } from '../ui-kit'

export function SettingsPage() {
  const { theme, setTheme, adminKey, setAdminKey, clearAdminKey, adminKeyPersisted } = useAppSettings()
  const { toast } = useToast()
  const healthQ = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 60_000 })

  const adminEnabled = Boolean(healthQ.data?.features?.admin?.enabled)
  const adminAuthMode = String(healthQ.data?.features?.admin?.auth_mode ?? 'key').toLowerCase()

  const [draftKey, setDraftKey] = React.useState(adminKey)

  React.useEffect(() => {
    setDraftKey(adminKey)
  }, [adminKey])

  return (
    <Page
      title="Settings"
      description="Local UI preferences + optional admin access for audit endpoints."
      actions={
        <div className="flex items-center gap-2">
          {healthQ.data ? <Badge variant="outline">env: {healthQ.data.env}</Badge> : null}
        </div>
      }
    >
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Appearance</CardTitle>
            <CardDescription>Theme is stored in localStorage.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium">Theme</div>
                <div className="text-xs text-muted-foreground">Current: {theme}</div>
              </div>
              <Button variant="outline" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
                Switch to {theme === 'dark' ? 'light' : 'dark'}
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Admin access</CardTitle>
            <CardDescription>
              Enables <code className="font-mono">/api/v1/admin/*</code> audit pages (ingestions, drift, notifications, exports).
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!healthQ.isSuccess ? (
              <div className="space-y-2">
                <Badge variant="outline">checking…</Badge>
                <div className="text-sm text-muted-foreground">Checking server capabilities…</div>
              </div>
            ) : !adminEnabled ? (
              <div className="space-y-2">
                <Badge variant="outline">admin routes disabled</Badge>
                <div className="text-sm text-muted-foreground">
                  This deployment was configured with <code className="font-mono">ENABLE_ADMIN_ROUTES=0</code>.
                  Use the dedicated admin service (recommended) or enable admin routes for this service.
                </div>
              </div>
            ) : adminAuthMode === 'none' ? (
              <div className="space-y-2">
                <Badge variant="success">admin protected by IAM</Badge>
                <div className="text-sm text-muted-foreground">
                  This deployment is configured with <code className="font-mono">ADMIN_AUTH_MODE=none</code>, meaning admin
                  endpoints trust an infrastructure perimeter (Cloud Run IAM / IAP / VPN). No shared admin key is required
                  in the browser.
                </div>
                <div className="text-xs text-muted-foreground">
                  Tip: Keep the public ingest service free of admin routes (<code className="font-mono">ENABLE_ADMIN_ROUTES=0</code>)
                  and deploy a separate private admin service.
                </div>
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  <Label>Admin key</Label>
                  <Input
                    type="password"
                    value={draftKey}
                    onChange={(e) => setDraftKey(e.target.value)}
                    placeholder="X-Admin-Key"
                  />
                  <div className="text-xs text-muted-foreground">
                    Stored in session by default. Persist only on trusted developer machines.
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    onClick={() => {
                      setAdminKey(draftKey, { persist: false })
                      toast({ title: 'Admin key saved', description: 'Stored for this session only.', variant: 'success' })
                    }}
                  >
                    Save (session)
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setAdminKey(draftKey, { persist: true })
                      toast({
                        title: 'Admin key persisted',
                        description: 'Stored in localStorage on this machine. Do not use on shared/public devices.',
                        variant: 'warning',
                        durationMs: 7000,
                      })
                    }}
                  >
                    Save + persist
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => {
                      clearAdminKey()
                      toast({ title: 'Admin key cleared', variant: 'default' })
                    }}
                  >
                    Clear
                  </Button>
                  {adminKey ? (
                    <Badge variant="success" className="ml-auto">
                      enabled{adminKeyPersisted ? ' (persisted)' : ''}
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="ml-auto">
                      disabled
                    </Badge>
                  )}
                </div>

                <div className="text-xs text-muted-foreground">
                  Tip: Start with <code className="font-mono">.env.example</code> → <code className="font-mono">ADMIN_API_KEY</code>.
                  You can create a demo device via <code className="font-mono">make demo-device</code>.
                </div>

                <div className="text-xs text-muted-foreground">
                  If you are deploying publicly, do not expose the admin key to browsers. Instead, keep admin endpoints
                  private (Cloud Run IAM/IAP) or use a separate admin service.
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Links</CardTitle>
          <CardDescription>Quick jump-off points.</CardDescription>
        </CardHeader>
        <CardContent className="space-x-4 text-sm">
          <Link to="/meta" className="underline">
            System info
          </Link>
          <a className="underline" href="/docs" target="_blank" rel="noreferrer">
            API docs
          </a>
        </CardContent>
      </Card>
    </Page>
  )
}
