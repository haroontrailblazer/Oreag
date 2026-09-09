import { Skeleton } from "@/components/ui/skeleton"

export function QueryRowsSkeleton() {
  return <div role="status" aria-label="Loading queries" className="divide-y">
    {Array.from({ length: 6 }, (_, index) => <div key={index} className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:gap-6">
      <div className="min-w-0 flex-1 space-y-2"><Skeleton className="h-5 w-4/5" /><Skeleton className="h-3 w-56 max-w-full" /></div>
      <div className="flex shrink-0 items-center gap-3"><Skeleton className="h-5 w-24 rounded-full" /><Skeleton className="ml-auto h-3 w-24" /><Skeleton className="size-4" /></div>
    </div>)}
  </div>
}

export function QueryDetailSkeleton() {
  return <div role="status" aria-label="Loading query details" className="min-h-0 flex-1 space-y-6 overflow-y-auto p-6 pt-2">
    <div className="space-y-2"><Skeleton className="h-3 w-40" /><Skeleton className="h-5 w-32" /></div>
    <div className="space-y-2"><Skeleton className="h-3 w-20" /><div className="space-y-3 rounded-xl border p-4"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-4/5" /></div></div>
    <div className="grid grid-cols-2 gap-3">{Array.from({ length: 6 }, (_, index) => <div key={index} className="min-w-0 space-y-3 rounded-xl border p-3"><Skeleton className="h-3 w-3/4" /><Skeleton className="h-5 w-2/3" /></div>)}</div>
    <div className="space-y-2"><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-4/5" /></div>
    <div className="space-y-2 rounded-xl border p-4"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-3/4" /></div>
    <Skeleton className="h-9 w-36" />
  </div>
}

export function QueryExplorerLoading() {
  return <div role="status" aria-label="Loading queries" className="flex h-[calc(100dvh-6.25rem)] min-h-0 min-w-0 flex-col gap-4 md:h-full">
    <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b pb-4"><div><h1 className="text-[1.75rem] font-semibold tracking-[-0.035em]">Queries</h1><p className="mt-1 text-sm text-muted-foreground">Find questions. Inspect latency, caching, and retrieval quality.</p></div><Skeleton className="h-8 w-24" /></header>
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-0.5 pb-3">
      <div className="shrink-0 rounded-xl border bg-card p-4 md:max-h-[40%] md:space-y-4 md:overflow-y-auto md:[@media(max-height:700px)]:max-h-[30%]">
        <div className="flex items-center gap-3"><Skeleton className="h-9 min-w-0 flex-1" /><Skeleton className="size-9 shrink-0 md:hidden" /></div>
        <div className="hidden grid-cols-2 gap-3 md:grid xl:grid-cols-4">{[0, 1, 2, 3].map(index => <div key={index} className="space-y-1.5"><Skeleton className="h-4 w-20" /><Skeleton className="h-9 w-full" /></div>)}</div>
      </div>
      <div className="flex max-h-full min-h-0 flex-col overflow-hidden rounded-xl border bg-card">
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b px-4 py-3"><h2 className="text-sm font-medium">Recent queries</h2><Skeleton className="h-3 w-36" /></div>
        <div className="min-h-0 overflow-y-auto"><QueryRowsSkeleton /></div>
        <div className="flex shrink-0 items-center justify-between gap-3 border-t px-4 py-3"><Skeleton className="h-3 w-12" /><div className="flex gap-2"><Skeleton className="h-8 w-20" /><Skeleton className="h-8 w-14" /></div></div>
      </div>
      <Skeleton className="h-3 w-full max-w-2xl shrink-0" />
    </div>
  </div>
}
