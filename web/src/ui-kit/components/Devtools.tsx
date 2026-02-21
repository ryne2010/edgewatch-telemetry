import React from 'react'

/**
 * Small in-app devtools wrapper.
 *
 * We keep this as a tiny, local abstraction so we can:
 * - disable or swap devtools cleanly
 * - keep app code free from deep react-query imports
 */
export function AppDevtools() {
  const env = (import.meta as any)?.env
  const isDev = env?.DEV === true
  const enable = env?.VITE_ENABLE_DEVTOOLS === '1'

  if (!isDev || !enable) return null

  // Lazy import avoids bundling devtools into production builds.
  const Devtools = React.lazy(async () => {
    const mod = await import('@tanstack/react-query-devtools')
    return { default: mod.ReactQueryDevtools }
  })

  return (
    <React.Suspense fallback={null}>
      <Devtools initialIsOpen={false} />
    </React.Suspense>
  )
}
