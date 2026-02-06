import React from 'react'

export type Point = { x: number; y: number }

export function LineChart(props: { points: Point[]; height?: number; title?: string; yAxisLabel?: string }) {
  const w = 900
  const h = props.height ?? 240
  const padLeft = 96
  const padRight = 24
  const padTop = 20
  const padBottom = 28

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

  const scaleX = (x: number) => padLeft + ((x - minX) / dx) * (w - padLeft - padRight)
  const scaleY = (y: number) => h - padBottom - ((y - minY) / dy) * (h - padTop - padBottom)

  const fmtY = (v: number) => {
    const av = Math.abs(v)
    if (av >= 100) return v.toFixed(0)
    if (av >= 10) return v.toFixed(1)
    return v.toFixed(2)
  }

  const ticks =
    minY === maxY
      ? (() => {
          const spread = Math.max(1, Math.abs(minY) * 0.1)
          return [minY + spread, minY, minY - spread]
        })()
      : [maxY, (minY + maxY) / 2, minY]

  const d = pts
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(p.x).toFixed(2)} ${scaleY(p.y).toFixed(2)}`)
    .join(' ')

  return (
    <div className="w-full">
      {props.title ? <div className="mb-2 text-xl font-semibold leading-none">{props.title}</div> : null}
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img" aria-label="line chart">
        {props.yAxisLabel ? (
          <text
            x={22}
            y={h / 2}
            transform={`rotate(-90 22 ${h / 2})`}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize="16"
            fill="currentColor"
            opacity="0.7"
          >
            {props.yAxisLabel}
          </text>
        ) : null}

        {ticks.map((t, i) => {
          const y = scaleY(t)
          return (
            <g key={i}>
              <line x1={padLeft} y1={y} x2={w - padRight} y2={y} stroke="currentColor" opacity="0.12" />
              <text
                x={padLeft - 8}
                y={y}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize="20"
                fill="currentColor"
                opacity="0.75"
              >
                {fmtY(t)}
              </text>
            </g>
          )
        })}
        <path d={d} fill="none" stroke="currentColor" strokeWidth="2" />
        <line
          x1={padLeft}
          y1={h - padBottom}
          x2={w - padRight}
          y2={h - padBottom}
          stroke="currentColor"
          opacity="0.2"
        />
        <line x1={padLeft} y1={padTop} x2={padLeft} y2={h - padBottom} stroke="currentColor" opacity="0.2" />
      </svg>
      <div className="mt-2 flex justify-between text-xs text-muted-foreground">
        <span className="font-mono">{new Date(minX).toLocaleTimeString()}</span>
        <span className="font-mono">{new Date(maxX).toLocaleTimeString()}</span>
      </div>
    </div>
  )
}
