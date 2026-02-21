import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider } from '@tanstack/react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { router } from './router'
import { AppSettingsProvider } from './app/settings'
import { ToastProvider } from './ui-kit/ui/toast'
import './styles.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <AppSettingsProvider>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </AppSettingsProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
