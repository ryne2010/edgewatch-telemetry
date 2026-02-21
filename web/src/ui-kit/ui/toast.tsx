import * as React from 'react'
import { X } from 'lucide-react'
import { cn } from '../lib/utils'

export type ToastVariant = 'default' | 'success' | 'warning' | 'error'

export type ToastInput = {
  title: string
  description?: string
  variant?: ToastVariant
  durationMs?: number
}

type Toast = Required<Pick<ToastInput, 'title'>> & {
  id: string
  description?: string
  variant: ToastVariant
  durationMs: number
  createdAt: number
}

type ToastContextValue = {
  toast: (t: ToastInput) => void
  dismiss: (id: string) => void
}

const ToastContext = React.createContext<ToastContextValue | null>(null)

function toastClasses(variant: ToastVariant): string {
  switch (variant) {
    case 'success':
      return 'border-emerald-200 bg-emerald-50 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-50'
    case 'warning':
      return 'border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-50'
    case 'error':
      return 'border-destructive/30 bg-destructive/10 text-foreground'
    default:
      return 'border-border bg-background text-foreground'
  }
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([])
  const timers = React.useRef<Map<string, number>>(new Map())

  const dismiss = React.useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    const tm = timers.current.get(id)
    if (tm) {
      window.clearTimeout(tm)
      timers.current.delete(id)
    }
  }, [])

  const toast = React.useCallback(
    (input: ToastInput) => {
      const id = (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`).toString()
      const t: Toast = {
        id,
        title: input.title,
        description: input.description,
        variant: input.variant ?? 'default',
        durationMs: input.durationMs ?? 5000,
        createdAt: Date.now(),
      }

      setToasts((prev) => {
        const next = [...prev, t]
        // guardrail: avoid infinite stacks
        return next.slice(-5)
      })

      const tm = window.setTimeout(() => dismiss(id), t.durationMs)
      timers.current.set(id, tm)
    },
    [dismiss],
  )

  const value = React.useMemo(() => ({ toast, dismiss }), [toast, dismiss])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <Toaster toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = React.useContext(ToastContext)
  if (!ctx) {
    throw new Error('useToast must be used within <ToastProvider>')
  }
  return ctx
}

function Toaster({
  toasts,
  onDismiss,
}: {
  toasts: Toast[]
  onDismiss: (id: string) => void
}) {
  return (
    <div
      className="fixed right-4 top-4 z-50 flex w-[min(420px,calc(100vw-2rem))] flex-col gap-2"
      aria-live="polite"
      aria-relevant="additions"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={cn(
            'rounded-lg border p-3 shadow-md backdrop-blur supports-[backdrop-filter]:bg-background/80',
            toastClasses(t.variant),
          )}
        >
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold leading-tight">{t.title}</div>
              {t.description ? (
                <div className="mt-1 text-sm text-muted-foreground">{t.description}</div>
              ) : null}
            </div>
            <button
              type="button"
              className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Dismiss"
              onClick={() => onDismiss(t.id)}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
