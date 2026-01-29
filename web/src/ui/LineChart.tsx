import React from 'react'

export type Point = { x: number; y: number }

export function LineChart(props: { points: Point[]; height?: number }) {
  const w = 900
  const h = props.height ?? 240
  const pad = 24

  const pts = props.points ?? []
  if (!pts.length) {
    return <div className="text-sm text-muted-foreground">No telemetry points.</div>
  }

  const xs = pts.map((p) => p.x)
  const ys = pts.map((p) => p.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)

  const dx = maxX - minX || 1
  const dy = maxY - minY || 1

  const scaleX = (x: number) => pad + ((x - minX) / dx) * (w - pad * 2)
  const scaleY = (y: number) => h - pad - ((y - minY) / dy) * (h - pad * 2)

  const d = pts
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(p.x).toFixed(2)} ${scaleY(p.y).toFixed(2)}`)
    .join(' ')

  return (
    <div className="w-full">
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img" aria-label="line chart">
        <path d={d} fill="none" stroke="currentColor" strokeWidth="2" />
        <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="currentColor" opacity="0.2" />
        <line x1={pad} y1={pad} x2={pad} y2={h - pad} stroke="currentColor" opacity="0.2" />
      </svg>
      <div className="mt-2 flex justify-between text-xs text-muted-foreground">
        <span className="font-mono">{new Date(minX).toLocaleTimeString()}</span>
        <span className="font-mono">{new Date(maxX).toLocaleTimeString()}</span>
      </div>
    </div>
  )
}
