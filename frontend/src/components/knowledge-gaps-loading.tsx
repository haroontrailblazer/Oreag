import { Skeleton } from "@/components/ui/skeleton"

export function KnowledgeGapsContentSkeleton() {
  return <div role="status" aria-label="Loading knowledge gaps" className="space-y-4">
    <div className="grid grid-cols-3 gap-2 sm:gap-3">{[0, 1, 2].map(index => <div key={index} className="min-w-0 space-y-3 rounded-xl border bg-card p-3 sm:p-4"><div className="h-8 sm:h-4"><Skeleton className="h-3 w-20 max-w-full" /></div><Skeleton className="h-7 w-10" /></div>)}</div>
    <Skeleton className="h-4 w-full max-w-lg" />
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3"><p className="text-sm font-medium">Question groups</p><Skeleton className="h-3 w-24" /></div>
      <div className="divide-y">{[0, 1, 2].map(index => <div key={index} className="space-y-3 px-4 py-4">
        <div className="flex flex-col justify-between gap-2 sm:flex-row"><Skeleton className="h-5 w-3/5" /><Skeleton className="h-5 w-24 rounded-full" /></div>
        <Skeleton className="h-4 w-4/5" />
        <div className="flex items-center justify-between gap-3"><Skeleton className="h-3 w-2/3" /><Skeleton className="size-4" /></div>
      </div>)}</div>
    </div>
  </div>
}

export function KnowledgeGapDetailSkeleton() {
  return <div role="status" aria-label="Loading gap details" className="space-y-6">
    <div className="flex gap-2"><Skeleton className="h-5 w-24 rounded-full" /><Skeleton className="h-5 w-32" /></div>
    <div className="space-y-2"><Skeleton className="h-3 w-20" /><div className="space-y-3 rounded-xl border p-4"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-4/5" /></div></div>
    <div className="grid grid-cols-2 gap-3">{[0, 1, 2, 3].map(index => <div key={index} className="min-w-0 space-y-3 rounded-xl border p-3"><Skeleton className="h-3 w-3/4" /><Skeleton className="h-6 w-12" /></div>)}</div>
    <Skeleton className="h-4 w-full" />
    <div className="space-y-3 rounded-xl border p-4"><Skeleton className="h-4 w-36" /><Skeleton className="h-24 w-full" /><Skeleton className="h-8 w-32" /></div>
  </div>
}

export function KnowledgeGapsLoading() {
  return <div className="flex h-[calc(100dvh-6.3125rem)] min-h-0 min-w-0 flex-col gap-4 md:h-full">
    <header className="grid shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 border-b pb-4">
      <h1 className="col-span-2 text-[1.75rem] font-semibold tracking-[-0.035em] lg:col-span-1">Knowledge gaps</h1>
      <p className="col-span-2 row-start-2 text-xs leading-5 text-muted-foreground md:text-sm">Find repeated questions that need better evidence. Review the queries, improve your documents, and track the fix.</p>
      <div className="col-span-2 row-start-3 flex min-w-0 gap-2 lg:col-span-1 lg:col-start-2 lg:row-start-1 lg:w-72"><Skeleton className="h-8 min-w-0 flex-1" /><Skeleton className="size-8 shrink-0" /><Skeleton className="size-8 shrink-0" /></div>
    </header>
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pb-3 pr-0.5"><Skeleton className="h-5 w-60 max-w-full" /><KnowledgeGapsContentSkeleton /></div>
  </div>
}
