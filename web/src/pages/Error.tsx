import * as React from 'react'

import { Button, Page, Separator } from '../ui-kit'

function safeString(value: unknown): string {
  try {
    if (value == null) return ''
    if (typeof value === 'string') return value
    if (value instanceof Error) return value.message
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // Fallback for older browsers / non-secure contexts.
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.setAttribute('readonly', 'true')
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      return true
    } catch {
      return false
    }
  }
}

export function ErrorPage({ error }: { error: unknown }) {
  const err = error as any
  const message = safeString(err?.message ?? err ?? 'Unknown error')
  const stack = safeString(err?.stack)

  const diag = React.useMemo(() => {
    const payload = {
      at: new Date().toISOString(),
      url: typeof window !== 'undefined' ? window.location.href : undefined,
      path: typeof window !== 'undefined' ? window.location.pathname : undefined,
      search: typeof window !== 'undefined' ? window.location.search : undefined,
      message,
      stack,
      userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : undefined,
    }
    return JSON.stringify(payload, null, 2)
  }, [message, stack])

  const [copied, setCopied] = React.useState<'idle' | 'ok' | 'fail'>('idle')

  const onCopy = async () => {
    const ok = await copyToClipboard(diag)
    setCopied(ok ? 'ok' : 'fail')
    window.setTimeout(() => setCopied('idle'), 2500)
  }

  return (
    <Page title="Something went wrong" description="The app hit an unexpected error.">
      <div className="max-w-3xl">
        <div className="flex flex-wrap gap-2">
          <Button variant="default" onClick={() => window.location.reload()}>
            Reload
          </Button>
          <Button variant="outline" onClick={() => (window.location.href = '/')}>
            Go home
          </Button>
          <Button variant="outline" onClick={onCopy}>
            {copied === 'ok' ? 'Copied' : copied === 'fail' ? 'Copy failed' : 'Copy diagnostics'}
          </Button>
        </div>

        <Separator className="my-6" />

        <div className="rounded-md border bg-muted/20 p-4">
          <div className="text-sm font-medium">Error</div>
          <div className="mt-1 text-sm text-muted-foreground">{message}</div>

          {stack ? (
            <>
              <div className="mt-4 text-sm font-medium">Stack</div>
              <pre className="mt-2 max-h-80 overflow-auto rounded bg-background p-3 text-xs">{stack}</pre>
            </>
          ) : null}

          <div className="mt-4 text-sm font-medium">Diagnostics</div>
          <pre className="mt-2 max-h-80 overflow-auto rounded bg-background p-3 text-xs">{diag}</pre>
        </div>
      </div>
    </Page>
  )
}
