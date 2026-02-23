import * as React from 'react'

type Theme = 'light' | 'dark'

const THEME_KEY = 'theme'
const ADMIN_KEY_SESSION = 'edgewatch_admin_key'
const ADMIN_KEY_PERSIST = 'edgewatch_admin_key_persist'
const ADMIN_KEY_LOCAL = 'edgewatch_admin_key_local'

function canPersistAdminKeyLocally(): boolean {
  try {
    const host = (globalThis.location?.hostname ?? '').toLowerCase()
    return host === 'localhost' || host === '127.0.0.1'
  } catch {
    return false
  }
}

function normalizeAdminKeyInput(raw: string): string {
  let value = (raw ?? '').trim()
  if (!value) return ''

  // Accept pastes like:
  // - ADMIN_API_KEY=abc123
  // - export ADMIN_API_KEY=abc123
  const assignMatch = /^(?:export\s+)?admin_api_key\s*=\s*(.+)$/i.exec(value)
  if (assignMatch) value = assignMatch[1].trim()

  // Strip a single pair of surrounding quotes.
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    value = value.slice(1, -1).trim()
  }

  return value
}

export type AppSettings = {
  theme: Theme
  setTheme: (t: Theme) => void

  /**
   * Optional admin key used for `/api/v1/admin/*` endpoints.
   * Stored in sessionStorage by default; can be persisted explicitly.
   */
  adminKey: string
  setAdminKey: (key: string, opts?: { persist?: boolean }) => void
  clearAdminKey: () => void
  adminKeyPersisted: boolean
}

const Ctx = React.createContext<AppSettings | null>(null)

function safeGet(storage: Storage, key: string): string {
  try {
    return storage.getItem(key) ?? ''
  } catch {
    return ''
  }
}

function safeSet(storage: Storage, key: string, value: string): void {
  try {
    storage.setItem(key, value)
  } catch {
    // ignore
  }
}

function safeRemove(storage: Storage, key: string): void {
  try {
    storage.removeItem(key)
  } catch {
    // ignore
  }
}

function getInitialTheme(): Theme {
  const stored = safeGet(localStorage, THEME_KEY)
  return stored === 'dark' ? 'dark' : 'light'
}

function getInitialAdminKey(): { key: string; persisted: boolean } {
  const sessionKey = normalizeAdminKeyInput(safeGet(sessionStorage, ADMIN_KEY_SESSION))
  if (sessionKey) return { key: sessionKey, persisted: false }

  if (!canPersistAdminKeyLocally()) {
    return { key: '', persisted: false }
  }

  const persist = safeGet(localStorage, ADMIN_KEY_PERSIST)
  if (persist === '1') {
    const localKey = normalizeAdminKeyInput(safeGet(localStorage, ADMIN_KEY_LOCAL))
    return { key: localKey, persisted: Boolean(localKey) }
  }

  return { key: '', persisted: false }
}

export function AppSettingsProvider(props: { children: React.ReactNode }) {
  const [theme, setTheme] = React.useState<Theme>(() => getInitialTheme())
  const [adminKeyState, setAdminKeyState] = React.useState(() => getInitialAdminKey())

  React.useEffect(() => {
    const root = document.documentElement
    if (theme === 'dark') root.classList.add('dark')
    else root.classList.remove('dark')
    safeSet(localStorage, THEME_KEY, theme)
  }, [theme])

  const setAdminKey = React.useCallback((key: string, opts?: { persist?: boolean }) => {
    const k = normalizeAdminKeyInput(key ?? '')
    const persist = Boolean(opts?.persist) && canPersistAdminKeyLocally()

    if (!k) {
      // Treat blank as a clear.
      safeRemove(sessionStorage, ADMIN_KEY_SESSION)
      safeSet(localStorage, ADMIN_KEY_PERSIST, '0')
      safeRemove(localStorage, ADMIN_KEY_LOCAL)
      setAdminKeyState({ key: '', persisted: false })
      return
    }

    // Always keep a session copy so a refresh doesn't immediately forget it.
    safeSet(sessionStorage, ADMIN_KEY_SESSION, k)

    if (persist) {
      safeSet(localStorage, ADMIN_KEY_PERSIST, '1')
      safeSet(localStorage, ADMIN_KEY_LOCAL, k)
    } else {
      safeSet(localStorage, ADMIN_KEY_PERSIST, '0')
      safeRemove(localStorage, ADMIN_KEY_LOCAL)
    }

    setAdminKeyState({ key: k, persisted: persist && Boolean(k) })
  }, [])

  const clearAdminKey = React.useCallback(() => {
    safeRemove(sessionStorage, ADMIN_KEY_SESSION)
    safeSet(localStorage, ADMIN_KEY_PERSIST, '0')
    safeRemove(localStorage, ADMIN_KEY_LOCAL)
    setAdminKeyState({ key: '', persisted: false })
  }, [])

  const value: AppSettings = React.useMemo(
    () => ({
      theme,
      setTheme,
      adminKey: adminKeyState.key,
      adminKeyPersisted: adminKeyState.persisted,
      setAdminKey,
      clearAdminKey,
    }),
    [theme, adminKeyState.key, adminKeyState.persisted, setAdminKey, clearAdminKey],
  )

  return <Ctx.Provider value={value}>{props.children}</Ctx.Provider>
}

export function useAppSettings(): AppSettings {
  const ctx = React.useContext(Ctx)
  if (!ctx) throw new Error('useAppSettings must be used within AppSettingsProvider')
  return ctx
}
