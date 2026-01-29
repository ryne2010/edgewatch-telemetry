import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Page } from '../portfolio-ui'

export function MetaPage() {
  const q = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15_000 })

  return (
    <Page title="Meta" description="Health + runtime diagnostics for the edge telemetry service.">
      <Card>
        <CardHeader>
          <CardTitle>Health</CardTitle>
          <CardDescription>Safe to expose for ops dashboards (no secrets).</CardDescription>
        </CardHeader>
        <CardContent>
          {q.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
          {q.isError ? <div className="text-sm text-destructive">Error: {(q.error as Error).message}</div> : null}
          {q.data ? (
            <pre className="overflow-x-auto rounded-md border bg-muted/30 p-4 text-xs">
{JSON.stringify(q.data, null, 2)}
            </pre>
          ) : null}
        </CardContent>
      </Card>
    </Page>
  )
}
