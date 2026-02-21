import * as React from 'react'
import { cn } from './lib/utils'

type IconProps = { className?: string }

export function IconDashboard(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={cn('h-5 w-5', props.className)} aria-hidden="true">
      <path
        fill="currentColor"
        d="M4 13a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v7H6a2 2 0 0 1-2-2v-5Zm10-9a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v16h-6V4ZM4 6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v3H4V6Zm10 7a2 2 0 0 1 2-2h4v9h-6v-7Z"
      />
    </svg>
  )
}

export function IconDevices(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={cn('h-5 w-5', props.className)} aria-hidden="true">
      <path
        fill="currentColor"
        d="M7 2h10a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2h-2v2H9v-2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Zm0 2v13h10V4H7Zm2 15h6v2H9v-2Z"
      />
    </svg>
  )
}

export function IconBell(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={cn('h-5 w-5', props.className)} aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm7-6V11a7 7 0 0 0-5-6.71V3a2 2 0 1 0-4 0v1.29A7 7 0 0 0 5 11v5l-2 2v1h18v-1l-2-2Z"
      />
    </svg>
  )
}

export function IconFile(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={cn('h-5 w-5', props.className)} aria-hidden="true">
      <path
        fill="currentColor"
        d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7l-5-5Zm1 7V3.5L19.5 9H15Zm-8 2h10v2H7v-2Zm0 4h10v2H7v-2Zm0 4h7v2H7v-2Z"
      />
    </svg>
  )
}

export function IconShield(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={cn('h-5 w-5', props.className)} aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5l-8-3Zm0 18.9c-3.5-1.3-6-5.1-6-9.9V6.3L12 4l6 2.3V11c0 4.8-2.5 8.6-6 9.9Z"
      />
    </svg>
  )
}

export function IconSettings(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={cn('h-5 w-5', props.className)} aria-hidden="true">
      <path
        fill="currentColor"
        d="M19.14 12.94c.04-.31.06-.63.06-.94s-.02-.63-.06-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7.3 7.3 0 0 0-1.63-.94l-.36-2.54A.5.5 0 0 0 13.9 1h-3.8a.5.5 0 0 0-.49.42l-.36 2.54c-.58.22-1.12.52-1.63.94l-2.39-.96a.5.5 0 0 0-.6.22L2.71 7.48a.5.5 0 0 0 .12.64l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94l-2.03 1.58a.5.5 0 0 0-.12.64l1.92 3.32c.13.23.4.32.64.22l2.39-.96c.5.41 1.05.73 1.63.94l.36 2.54c.05.24.25.42.49.42h3.8c.24 0 .44-.18.48-.42l.36-2.54c.58-.22 1.12-.52 1.63-.94l2.39.96c.24.1.51.01.64-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58ZM12 15.5A3.5 3.5 0 1 1 12 8a3.5 3.5 0 0 1 0 7.5Z"
      />
    </svg>
  )
}

export function IconInfo(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={cn('h-5 w-5', props.className)} aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 15a1 1 0 0 1-1-1v-5a1 1 0 1 1 2 0v5a1 1 0 0 1-1 1Zm0-9a1.25 1.25 0 1 1 0-2.5A1.25 1.25 0 0 1 12 8Z"
      />
    </svg>
  )
}
