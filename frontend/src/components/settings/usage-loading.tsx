import { Skeleton } from "@/components/ui/skeleton"

export function UsageInsightsSkeleton() {
  return (
    <div className="min-w-0 shrink-0 space-y-4 rounded-2xl border border-border/80 bg-muted/20 p-4 sm:p-5" role="status" aria-label="Loading usage insights">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-2"><Skeleton className="h-6 w-40" /><Skeleton className="h-4 w-full max-w-xl" /></div>
        <Skeleton className="h-8 w-36" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map(index => <div key={index} className="usage-insight-card min-w-0 space-y-3 rounded-xl border border-border/70 bg-background/80 p-4 sm:p-5">
          <div className="flex min-h-8 items-start gap-2"><Skeleton className="size-4 shrink-0" /><Skeleton className="h-3 w-3/4" /></div>
          <Skeleton className="h-7 w-2/3" /><Skeleton className="h-6 w-28 max-w-full" />
          <div className="space-y-2"><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-4/5" /></div>
        </div>)}
      </div>
      <div className="min-w-0 overflow-hidden rounded-xl border border-border/70 bg-background/80" aria-hidden="true">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-4 py-3 sm:px-5">
          <Skeleton className="h-5 w-52 max-w-full" /><Skeleton className="h-5 w-24 rounded-full" />
        </div>
        <div className="grid min-w-0 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.6fr)]">
          <div className="min-w-0 space-y-4 p-4 sm:p-5">
            <Skeleton className="h-7 w-64 max-w-full" /><Skeleton className="h-8 w-full" />
            <div className="grid gap-3 rounded-lg border border-border/60 p-3 min-[400px]:grid-cols-2">
              {[0, 1].map(index => <div key={index} className="min-w-0 space-y-2"><Skeleton className="h-3 w-24 max-w-full" /><Skeleton className="h-7 w-20" /><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-full" /></div>)}
            </div>
            {[0, 1].map(index => <div key={index} className="flex gap-3"><Skeleton className="size-8 shrink-0 rounded-lg" /><div className="min-w-0 flex-1 space-y-2"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-4/5" /></div></div>)}
            <Skeleton className="h-5 w-full" /><Skeleton className="h-12 w-full" /><Skeleton className="h-4 w-44 max-w-full" />
          </div>
          <div className="min-w-0 space-y-3 border-t border-border/60 bg-muted/20 p-4 sm:p-5 xl:border-l xl:border-t-0">
            <Skeleton className="h-5 w-40 max-w-full" /><Skeleton className="h-8 w-28" /><Skeleton className="h-4 w-40 max-w-full" />
            <Skeleton className="h-12 w-full" /><Skeleton className="h-16 w-full" />
          </div>
        </div>
      </div>
      <Skeleton className="h-4 w-full max-w-3xl" />
    </div>
  )
}

export function UsageChartSkeleton({ label, kind = "chart" }: { label?: string; kind?: "chart" | "table" | "spend" | "savings" }) {
  return <div className="usage-loading-card flex min-w-0 shrink-0 flex-col gap-5 overflow-hidden rounded-xl border border-border bg-card py-6">
    <div className="shrink-0 space-y-2 border-b px-6 pb-5">
      {label ? <p className="text-sm font-medium">{label}</p> : <Skeleton className="h-5 w-40" />}
      <Skeleton className="h-4 w-4/5" />
    </div>
    <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-hidden px-6">
      {kind === "table" ? <div className="divide-y rounded-lg border">{Array.from({ length: 6 }, (_, index) => <div key={index} className="flex justify-between gap-4 p-3"><Skeleton className="h-4 w-2/5" /><Skeleton className="h-4 w-1/5" /><Skeleton className="h-4 w-1/5" /></div>)}</div>
      : kind === "spend" ? <><Skeleton className="h-10 w-32" /><div className="flex min-h-0 flex-1 flex-wrap items-center gap-6"><div className="relative size-36 shrink-0"><Skeleton className="size-full rounded-full" /><div className="absolute inset-6 rounded-full bg-card" /></div><div className="min-w-24 flex-1 space-y-5">{[0, 1].map(index => <div key={index} className="space-y-2"><Skeleton className="h-3 w-20" /><Skeleton className="h-5 w-24" /></div>)}</div></div></>
      : kind === "savings" ? <><Skeleton className="h-10 w-36" /><Skeleton className="h-4 w-3/4" /><Skeleton className="h-3 w-full rounded-full" /><div className="grid flex-1 grid-cols-2 gap-4">{[0, 1].map(index => <div key={index} className="space-y-3 rounded-xl border p-4"><Skeleton className="h-3 w-3/4" /><Skeleton className="h-7 w-2/3" /><Skeleton className="h-3 w-full" /></div>)}</div></>
      : <><div className="flex justify-between"><Skeleton className="h-7 w-24" /><Skeleton className="h-5 w-20" /></div><div className="flex min-h-24 flex-1 items-end gap-3 border-b border-l p-3">{[45, 65, 38, 78, 56, 88, 63, 74].map((height, index) => <Skeleton key={index} className="min-w-0 flex-1 rounded-b-none" style={{ height: height + "%" }} />)}</div><div className="flex justify-between"><Skeleton className="h-3 w-16" /><Skeleton className="h-3 w-16" /><Skeleton className="h-3 w-16" /></div></>}
      <div className="mt-auto grid shrink-0 grid-cols-2 gap-4 border-t pt-4">{[0, 1].map(index => <div key={index} className="space-y-2"><Skeleton className="h-3 w-3/4" /><Skeleton className="h-5 w-1/2" /></div>)}</div>
    </div>
  </div>
}

export function UsageDetailsSkeleton() {
  return (
    <div className="flex min-w-0 shrink-0 flex-col gap-6 sm:gap-8" role="status" aria-label="Loading usage details">
      <div className="usage-summary-grid grid grid-cols-2 overflow-hidden rounded-2xl border border-border bg-card shadow-sm xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, index) => <div key={index} className="usage-metric-card flex flex-col gap-4 p-5">
          <div className="flex items-center gap-3"><Skeleton className="size-9 shrink-0 rounded-xl" /><Skeleton className="h-3 w-16" /></div>
          <Skeleton className="h-8 w-4/5" /><Skeleton className="h-3 w-full" /><Skeleton className="mt-auto h-3 w-3/4" />
        </div>)}
      </div>
      <div className="grid gap-4 lg:grid-cols-2"><UsageChartSkeleton kind="spend" label="Where the money goes" /><UsageChartSkeleton kind="savings" label="Cache savings" /></div>
    </div>
  )
}

export function UsageLoading() {
  return (
    <div className="usage-dashboard flex h-[calc(100dvh-6.3125rem)] min-h-0 flex-col gap-4 overflow-hidden md:h-full" role="status" aria-label="Loading usage">
      <div className="usage-dashboard-header flex shrink-0 flex-wrap items-center justify-between gap-4 border-b border-border/70 pb-4 sm:pb-5">
        <div><h1 className="text-[1.75rem] font-semibold leading-tight tracking-[-0.035em]">Usage</h1><p className="mt-1 text-xs leading-relaxed text-muted-foreground sm:text-sm">Requests, tokens and cost across your API keys, models and projects.</p></div>
        <div className="flex h-10 items-center gap-1 rounded-xl border border-border/80 bg-muted/60 p-1">{[0, 1, 2].map(index => <Skeleton key={index} className="h-8 w-[4.5rem] rounded-lg" />)}</div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pb-2 sm:gap-6"><UsageInsightsSkeleton /><UsageDetailsSkeleton /></div>
    </div>
  )
}
