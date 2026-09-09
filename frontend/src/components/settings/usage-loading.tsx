import { Skeleton } from "@/components/ui/skeleton"

export function UsageInsightsSkeleton() {
  return (
    <div className="space-y-4 rounded-2xl border border-border p-4 sm:p-5" role="status" aria-label="Loading usage insights">
      <Skeleton className="h-12 rounded-lg" />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[1, 2, 3, 4].map((index) => <Skeleton key={index} className="usage-insight-card rounded-xl" />)}
      </div>
      <Skeleton className="h-8 rounded-lg" />
    </div>
  )
}

export function UsageDetailsSkeleton() {
  return (
    <div className="grid gap-4" role="status" aria-label="Loading usage details">
      <Skeleton className="usage-loading-summary rounded-xl" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="usage-loading-card rounded-xl" />
        <Skeleton className="usage-loading-card rounded-xl" />
      </div>
    </div>
  )
}

export function UsageLoading() {
  return (
    <div className="usage-dashboard flex min-h-0 flex-col gap-5">
      <div className="usage-dashboard-header border-b border-border/70 pb-5">
        <h1 className="text-[1.75rem] font-semibold leading-tight tracking-[-0.035em]">Usage</h1>
        <p className="mt-1 text-sm text-muted-foreground">Requests, tokens and cost across your API keys, models and projects.</p>
      </div>
      <UsageInsightsSkeleton />
      <UsageDetailsSkeleton />
    </div>
  )
}
