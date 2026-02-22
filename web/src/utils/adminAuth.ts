function toErrorMessage(error: unknown): string {
  if (!error) return ''
  if (error instanceof Error) return error.message
  return String(error)
}

export function httpStatusFromError(error: unknown): number | null {
  const message = toErrorMessage(error)
  const match = /\b([1-5]\d{2})\b/.exec(message)
  if (!match) return null
  const value = Number(match[1])
  return Number.isFinite(value) ? value : null
}

export function adminAccessHint(error: unknown, adminAuthMode: string | null | undefined): string | null {
  const status = httpStatusFromError(error)
  if (status !== 401 && status !== 403) return null

  const mode = String(adminAuthMode ?? 'key').toLowerCase()
  if (mode === 'none') {
    if (status === 401) {
      return 'Sign in through your IAM/IAP perimeter for this service, then refresh and retry.'
    }
    return 'Your identity is authenticated but not authorized for this view. Ask a platform admin to grant the required role.'
  }

  if (status === 401) {
    return 'The admin key is missing or invalid. Update it in Settings, then retry.'
  }
  return 'The request is authenticated but this identity is not authorized for this view.'
}
