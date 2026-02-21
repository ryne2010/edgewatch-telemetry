export function fmtDateTime(ts: string | null | undefined): string {
  if (!ts) return '—'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return String(ts)
  return d.toLocaleString()
}

export function fmtTime(ts: string | number | Date): string {
  const d = ts instanceof Date ? ts : new Date(ts)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString()
}

export function fmtTimeShort(ts: string | number | Date): string {
  const d = ts instanceof Date ? ts : new Date(ts)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function fmtDateShort(ts: string | number | Date): string {
  const d = ts instanceof Date ? ts : new Date(ts)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString()
}

export function fmtNumber(v: unknown, opts?: { digits?: number }): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '—'
  const digits = opts?.digits ?? 2
  if (Math.abs(v) >= 100) return v.toFixed(0)
  if (Math.abs(v) >= 10) return v.toFixed(1)
  return v.toFixed(Math.min(2, digits))
}

export function fmtBool(v: unknown): string {
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  return '—'
}

export function timeAgo(ts: string | null | undefined): string {
  if (!ts) return '—'
  const d = new Date(ts)
  const t = d.getTime()
  if (!Number.isFinite(t)) return '—'
  const sec = Math.floor((Date.now() - t) / 1000)
  if (sec < 5) return 'just now'
  if (sec < 60) return `${sec}s ago`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 48) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  return `${day}d ago`
}


export function fmtAlertType(value: string | null | undefined): string {
  if (!value) return '—'
  const parts = String(value)
    .trim()
    .split('_')
    .filter(Boolean)
  if (!parts.length) return '—'

  return parts
    .map((part) => {
      const upper = part.toUpperCase()
      if (upper === 'OK') return 'OK'
      if (upper === 'RSSI') return 'RSSI'
      return upper.slice(0, 1) + upper.slice(1).toLowerCase()
    })
    .join(' ')
}

