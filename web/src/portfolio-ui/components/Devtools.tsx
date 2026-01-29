import * as React from 'react'
import { TanStackDevtools } from '@tanstack/react-devtools'
import { ReactQueryDevtoolsPanel } from '@tanstack/react-query-devtools'
import { TanStackRouterDevtoolsPanel } from '@tanstack/react-router-devtools'
import { pacerDevtoolsPlugin } from '@tanstack/react-pacer-devtools'

export function PortfolioDevtools() {
  if (!import.meta.env.DEV) return null

  return (
    <TanStackDevtools
      plugins={[
        {
          name: 'TanStack Query',
          render: <ReactQueryDevtoolsPanel />,
        },
        {
          name: 'TanStack Router',
          render: <TanStackRouterDevtoolsPanel />,
        },
        pacerDevtoolsPlugin(),
      ]}
      eventBusConfig={{ debug: false }}
    />
  )
}
