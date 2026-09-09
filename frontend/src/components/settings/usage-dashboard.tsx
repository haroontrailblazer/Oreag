"use client"

import dynamic from "next/dynamic"
import { useState } from "react"
import useSWR from "swr"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { UsageInsights } from "@/components/settings/usage-insights"
import { UsageDetailsSkeleton, UsageInsightsSkeleton } from "@/components/settings/usage-loading"
import { fetcher, isSessionExpired } from "@/lib/api"
import {
  DEFAULT_USAGE_WINDOW,
  USAGE_REFRESH_MS,
  USAGE_WINDOWS,
  usageKey,
  type UsageWindow,
} from "@/lib/settings-data"
import type { AccountUsage } from "@/lib/types"
import { cn } from "@/lib/utils"

// Chart code is not a dependency of the route shell or the insights panel.
const UsageDetails = dynamic(
  () => import("@/components/settings/usage-dashboard-content").then((module) => module.UsageDetails),
  { loading: () => <UsageDetailsSkeleton /> }
)

export function UsageView({ data }: { data: AccountUsage }) {
  return (
    <div className="usage-dashboard-content flex min-w-0 flex-col gap-6 sm:gap-8">
      {data.totals.requests > 0 && <UsageInsights data={data} />}
      <UsageDetails data={data} />
    </div>
  )
}

export function UsageDashboard() {
  const [days, setDays] = useState<UsageWindow>(DEFAULT_USAGE_WINDOW)
  const { data, error, isLoading } = useSWR<AccountUsage>(
    usageKey(days),
    fetcher,
    {
      // Hold the previous window's render while the new one loads - no skeleton
      // flash, no layout jump; the content just dims briefly (below).
      keepPreviousData: true,
      // Poll the window actually on screen. The sidebar polls the default one
      // wherever the user is; this covers 7 and 90 while they are selected.
      refreshInterval: USAGE_REFRESH_MS,
    }
  )

  return (
    // Fixed frame like the sibling settings pages: the heading and range
    // selector never move, only the content below scrolls.
    <div className="usage-dashboard flex h-[calc(100dvh-6.25rem)] min-h-0 flex-col gap-4 overflow-hidden md:h-full">
      <div className="usage-dashboard-header flex shrink-0 flex-wrap items-center justify-between gap-4 border-b border-border/70 pb-4 sm:pb-5">
        <div>
          <h1 className="text-[1.75rem] font-semibold leading-tight tracking-[-0.035em]">Usage</h1>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground sm:text-sm">
            Requests, tokens and cost across your API keys, models and
            projects.
          </p>
        </div>
        <Tabs
          value={String(days)}
          onValueChange={(value) => setDays(Number(value) as UsageWindow)}
        >
          <TabsList className="h-10 rounded-xl border border-border/80 bg-muted/60 p-1 shadow-sm">
            {USAGE_WINDOWS.map((window) => (
              <TabsTrigger key={window} value={String(window)} className="rounded-lg px-3.5 text-xs font-semibold data-[state=active]:shadow-sm">
                {window} days
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      {/* Signed out is not a load failure - see lib/api.ts isSessionExpired. */}
      {error && !isSessionExpired(error) && (
        <p className="shrink-0 text-sm text-destructive">
          Could not load usage: {error.message}
        </p>
      )}

      {isLoading && !data && (
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pb-2 sm:gap-6">
          <UsageInsightsSkeleton />
          <UsageDetailsSkeleton />
        </div>
      )}

      {data && (
        <div
          className={cn(
            "usage-scroll min-h-0 flex-1 overflow-y-auto pb-3 pr-0.5",
            isLoading && "opacity-60 transition-opacity"
          )}
        >
          <UsageView data={data} />
        </div>
      )}
    </div>
  )
}
