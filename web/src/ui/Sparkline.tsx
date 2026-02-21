import React from 'react'
import type { Point } from './LineChart'

export type SparklineProps = {
  points: Point[]
  height?: number
  strokeWidth?: number
  className?: string
  ariaLabel?: string
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n))
}

export function Sparkline(props: SparklineProps) {
  const height = props.height ?? 64
  const strokeWidth = props.strokeWidth ?? 2

  const pts = React.useMemo(() => {
    const p = (props.points ?? []).filter((x) => Number.isFinite(x.x) && Number.isFinite(x.y))
    // Ensure chronological order.
    return p.slice().sort((a, b) => a.x - b.x)
  }, [props.points])

  if (!pts.length) {
    return (
      <div
        className={
          'flex items-center justify-center rounded-md border border-dashed bg-muted/30 text-xs text-muted-foreground ' +
          (props.className ?? '')
        }
        style={{ height }}
        aria-label={props.ariaLabel ?? 'sparkline'}
      >
        —
      </div>
    )
  }

  const W = 120
  const H = 40
  const PAD = 2

  const xMin = pts[0]?.x ?? 0
  const xMax = pts[pts.length - 1]?.x ?? xMin + 1

  let yMin = Infinity
  let yMax = -Infinity
  for (const p of pts) {
    yMin = Math.min(yMin, p.y)
    yMax = Math.max(yMax, p.y)
  }

  if (!Number.isFinite(yMin) || !Number.isFinite(yMax)) {
    yMin = 0
    yMax = 1
  }

  // Avoid flatline divide-by-zero.
  if (yMax - yMin < 1e-9) {
    yMax = yMin + 1
  }

  const xScale = (x: number) => {
    const t = (x - xMin) / (xMax - xMin || 1)
    return PAD + t * (W - PAD * 2)
  }

  const yScale = (y: number) => {
    const t = (y - yMin) / (yMax - yMin)
    // SVG y is top-down.
    return H - PAD - t * (H - PAD * 2)
  }

  const d = pts
    .map((p, i) => {
      const x = clamp(xScale(p.x), 0, W)
      const y = clamp(yScale(p.y), 0, H)
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`
    })
    .join(' ')

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className={'w-full ' + (props.className ?? '')}
      style={{ height }}
      role="img"
      aria-label={props.ariaLabel ?? 'sparkline'}
    >
      <path d={d} fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}
