import { useQuery } from '@tanstack/react-query'
import { api } from '../api'

type UseAdminAccessArgs = {
  adminEnabled: boolean
  adminAuthMode: string | null | undefined
  adminKey: string | null | undefined
}

function keyCacheFingerprint(value: string): string {
  let h = 2166136261
  for (let i = 0; i < value.length; i += 1) {
    h ^= value.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return `${value.length}:${(h >>> 0).toString(16)}`
}

export function useAdminAccess(args: UseAdminAccessArgs) {
  const mode = String(args.adminAuthMode ?? 'key').toLowerCase()
  const normalizedKey = (args.adminKey ?? '').trim()
  const enabled = Boolean(args.adminEnabled)
  const keyMode = mode === 'key'
  const hasKey = Boolean(normalizedKey)
  const keyFingerprint = hasKey ? keyCacheFingerprint(normalizedKey) : 'none'

  const keyValidationQ = useQuery({
    queryKey: ['admin', 'key-validation', keyFingerprint],
    queryFn: () => api.admin.events(normalizedKey, { limit: 1 }),
    enabled: enabled && keyMode && hasKey,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    retry: false,
  })

  const keyRequired = enabled && keyMode && !hasKey
  const keyValidating = enabled && keyMode && hasKey && (keyValidationQ.isLoading || keyValidationQ.isFetching)
  const keyValid = mode === 'none' ? true : hasKey && keyValidationQ.isSuccess
  const keyInvalid = enabled && keyMode && hasKey && keyValidationQ.isError

  const adminAccess = enabled && (mode === 'none' || keyValid)
  const adminCred = keyMode ? normalizedKey : ''

  return {
    adminAccess,
    adminCred,
    keyRequired,
    keyValid,
    keyValidating,
    keyInvalid,
    keyValidationError: keyValidationQ.error,
  }
}
