import * as React from 'react'
import { cn } from '../lib/utils'

export type PageProps = {
  title: string
  description?: React.ReactNode
  actions?: React.ReactNode
  children: React.ReactNode
  className?: string
}

export function Page({ title, description, actions, children, className }: PageProps) {
  return (
    <div className={cn('space-y-6', className)}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {description ? <div className="text-sm text-muted-foreground">{description}</div> : null}
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </div>
  )
}
