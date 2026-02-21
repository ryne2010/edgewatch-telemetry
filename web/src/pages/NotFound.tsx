import React from 'react'
import { Link } from '@tanstack/react-router'
import { Page } from '../ui-kit'

export function NotFoundPage() {
  return (
    <Page title="Not found" description="The page you requested does not exist.">
      <div className="rounded-lg border bg-muted/30 p-6">
        <div className="text-sm text-muted-foreground">Check the URL, or go back to:</div>
        <div className="mt-2">
          <Link to="/" className="underline">
            Dashboard
          </Link>
        </div>
      </div>
    </Page>
  )
}
