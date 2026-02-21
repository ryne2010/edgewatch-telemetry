import React from 'react'

export type Point = { x: number; y: number }

export type LineChartProps = {
  points: Point[]
  height?: number
  title?: string
  yAxisLabel?: string
  valueFormatter?: (v: number) => string
  timeFormatter?: (ms: number) => string
}

function defaultValueFormatter(v: number): string {
  const av = Math.abs(v)
  if (av >= 100) return v.toFixed(0)
  if (av >= 10) return v.toFixed(1)
  return v.toFixed(2)
}

function defaultTimeFormatter(ms: number): string {
  const d = new Date(ms)
  return d.toLocaleString()
}

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n))
}

export function LineChart(props: LineChartProps) {
  const w = 900
  const h = props.height ?? 260
  const padLeft = 96
  const padRight = 24
  const padTop = 18
  const padBottom = 34

  const fmtY = props.valueFormatter ?? defaultValueFormatter
  const fmtT = props.timeFormatter ?? defaultTimeFormatter

  const pts = React.useMemo(() => {
    const p = (props.points ?? []).slice()
    p.sort((a, b) => a.x - b.x)
    return p
  }, [props.points])

  const svgRef = React.useRef<SVGSVGElement | null>(null)
  const [hoverIndex, setHoverIndex] = React.useState<number | null>(null)

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

  const plotW = w - padLeft - padRight
  const plotH = h - padTop - padBottom

  const scaleX = (x: number) => padLeft + ((x - minX) / dx) * plotW
  const scaleY = (y: number) => h - padBottom - ((y - minY) / dy) * plotH
  const invScaleX = (sx: number) => minX + ((sx - padLeft) / plotW) * dx

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

  const onMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    const px = e.clientX - rect.left
    // Convert to viewBox space.
    const sx = (px / rect.width) * w
    const x = invScaleX(clamp(sx, padLeft, w - padRight))

    // Binary search nearest point.
    let lo = 0
    let hi = pts.length - 1
    while (lo < hi) {
      const mid = Math.floor((lo + hi) / 2)
      if (pts[mid].x < x) lo = mid + 1
      else hi = mid
    }
    const idx = lo
    const prev = idx > 0 ? idx - 1 : idx
    const nearest = Math.abs(pts[prev].x - x) <= Math.abs(pts[idx].x - x) ? prev : idx
    setHoverIndex(nearest)
  }

  const onMouseLeave = () => setHoverIndex(null)

  const hover = hoverIndex != null ? pts[hoverIndex] : null
  const hoverX = hover ? scaleX(hover.x) : null
  const hoverY = hover ? scaleY(hover.y) : null

  const minLabel = fmtT(minX)
  const maxLabel = fmtT(maxX)

  // Tooltip layout in SVG coordinates.
  const tooltip = hover
    ? (() => {
        const lines = [fmtT(hover.x), `${fmtY(hover.y)}`]
        const maxChars = Math.max(...lines.map((s) => s.length))
        const boxW = clamp(8 * maxChars + 18, 120, 260)
        const boxH = 46
        const pad = 10
        const x = clamp((hoverX ?? 0) + 14, padLeft + 6, w - padRight - boxW)
        const y = clamp((hoverY ?? 0) - boxH - 14, padTop + 6, h - padBottom - boxH)
        return { x, y, w: boxW, h: boxH, lines }
      })()
    : null

  return (
    <div className="w-full">
      {props.title ? <div className="mb-2 text-xl font-semibold leading-none">{props.title}</div> : null}
      <svg
        ref={svgRef}
        viewBox={`0 0 ${w} ${h}`}
        width="100%"
        height={h}
        role="img"
        aria-label="line chart"
        onMouseMove={onMouseMove}
        onMouseLeave={onMouseLeave}
      >
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

        {/* Grid + y ticks */}
        {ticks.map((t, i) => {
          const y = scaleY(t)
          return (
            <g key={i}>
              <line x1={padLeft} y1={y} x2={w - padRight} y2={y} stroke="currentColor" opacity="0.10" />
              <text
                x={padLeft - 8}
                y={y}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize="18"
                fill="currentColor"
                opacity="0.75"
              >
                {fmtY(t)}
              </text>
            </g>
          )
        })}

        {/* Axes */}
        <line
          x1={padLeft}
          y1={h - padBottom}
          x2={w - padRight}
          y2={h - padBottom}
          stroke="currentColor"
          opacity="0.2"
        />
        <line x1={padLeft} y1={padTop} x2={padLeft} y2={h - padBottom} stroke="currentColor" opacity="0.2" />

        {/* Series */}
        <path d={d} fill="none" stroke="currentColor" strokeWidth="2" />

        {/* Hover */}
        {hover && hoverX != null && hoverY != null ? (
          <g>
            <line x1={hoverX} y1={padTop} x2={hoverX} y2={h - padBottom} stroke="currentColor" opacity="0.15" />
            <circle cx={hoverX} cy={hoverY} r={4} fill="currentColor" opacity="0.9" />
          </g>
        ) : null}

        {/* Tooltip */}
        {tooltip ? (
          <g>
            <rect
              x={tooltip.x}
              y={tooltip.y}
              width={tooltip.w}
              height={tooltip.h}
              rx={10}
              fill="currentColor"
              opacity={0.08}
            />
            <rect
              x={tooltip.x}
              y={tooltip.y}
              width={tooltip.w}
              height={tooltip.h}
              rx={10}
              fill="none"
              stroke="currentColor"
              opacity={0.12}
            />
            <text x={tooltip.x + 12} y={tooltip.y + 18} fontSize={14} fill="currentColor" opacity={0.9}>
              {tooltip.lines[0]}
            </text>
            <text x={tooltip.x + 12} y={tooltip.y + 36} fontSize={16} fill="currentColor" opacity={0.95}>
              {tooltip.lines[1]}
            </text>
          </g>
        ) : null}

        {/* Hit area */}
        <rect x={padLeft} y={padTop} width={plotW} height={plotH} fill="transparent" />
      </svg>

      <div className="mt-2 flex justify-between text-xs text-muted-foreground">
        <span className="font-mono">{minLabel}</span>
        <span className="font-mono">{maxLabel}</span>
      </div>
    </div>
  )
}
