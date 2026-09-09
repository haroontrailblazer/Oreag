import { Skeleton } from "@/components/ui/skeleton"

export function UsageDetailsSkeleton() {
  return (
    <div className="grid gap-4" role="status" aria-label="Loading usage details">
      <Skeleton className="h-36 rounded-xl" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-80 rounded-xl" />
        <Skeleton className="h-80 rounded-xl" />
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
      <Skeleton className="h-64 rounded-2xl" />
      <UsageDetailsSkeleton />
    </div>
  )
}
