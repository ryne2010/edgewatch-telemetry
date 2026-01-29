import * as React from 'react'
import { useRanger, type Ranger } from '@tanstack/react-ranger'
import { cn } from '../lib/utils'

export type RangeSliderProps = {
  min: number
  max: number
  step: number
  value: number
  onChange: (next: number) => void
  label?: string
  className?: string
  format?: (n: number) => string
}

export function RangeSlider(props: RangeSliderProps) {
  const trackRef = React.useRef<HTMLDivElement>(null)
  const [values, setValues] = React.useState<ReadonlyArray<number>>([props.value])

  React.useEffect(() => {
    setValues([props.value])
  }, [props.value])

  const ranger = useRanger<HTMLDivElement>({
    getRangerElement: () => trackRef.current,
    values,
    min: props.min,
    max: props.max,
    stepSize: props.step,
    onChange: (instance: Ranger<HTMLDivElement>) => {
      const v = instance.sortedValues[0] ?? props.value
      setValues(instance.sortedValues)
      props.onChange(v)
    },
  })

  const display = props.format ? props.format(values[0] ?? props.value) : String(values[0] ?? props.value)

  return (
    <div className={cn('space-y-2', props.className)}>
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">{props.label ?? 'Value'}</span>
        <span className="font-mono text-xs">{display}</span>
      </div>

      <div
        ref={trackRef}
        className="relative h-2 w-full rounded-full bg-muted"
        style={{ userSelect: 'none' }}
      >
        {ranger.handles().map((handle, i) => (
          <button
            key={i}
            onKeyDown={handle.onKeyDownHandler}
            onMouseDown={handle.onMouseDownHandler}
            onTouchStart={handle.onTouchStart}
            role="slider"
            aria-label={props.label ?? 'slider'}
            aria-valuemin={ranger.options.min}
            aria-valuemax={ranger.options.max}
            aria-valuenow={handle.value}
            className={cn(
              'absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border bg-background shadow',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
            )}
            style={{ left: `${ranger.getPercentageForValue(handle.value)}%` }}
          />
        ))}
      </div>
    </div>
  )
}
