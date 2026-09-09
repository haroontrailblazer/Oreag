import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

function Heading({ title, description }: { title: string; description?: string }) {
  return <div className="shrink-0">
    <h1 className="text-2xl font-semibold">{title}</h1>
    {description && <p className="text-sm text-muted-foreground">{description}</p>}
  </div>
}

function Field({ tall = false }: { tall?: boolean }) {
  return <div className="space-y-2"><Skeleton className="h-3.5 w-28" /><Skeleton className={tall ? "h-16 w-full" : "h-9 w-full"} /></div>
}

export function ProjectCardsSkeleton() {
  return <div role="status" aria-label="Loading projects" className="grid min-h-0 flex-1 grid-cols-1 content-start gap-4 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
    {[0, 1, 2].map(index => <Card key={index}>
      <CardHeader>
        <div className="flex items-start justify-between gap-3"><Skeleton className="h-4 w-3/5" /><Skeleton className="h-6 w-16 rounded-full" /></div>
        <div className="space-y-1.5"><Skeleton className="h-3.5 w-full" /><Skeleton className="h-3.5 w-2/3" /></div>
      </CardHeader>
      <CardContent className="mt-auto flex gap-3"><Skeleton className="h-5 w-16" /><Skeleton className="h-5 w-20" /><Skeleton className="h-5 w-14" /></CardContent>
    </Card>)}
  </div>
}

export function OverviewLoading() {
  return <div className="flex h-[calc(100dvh-6.25rem)] min-h-0 flex-col gap-6 overflow-hidden md:h-full">
    <div className="flex shrink-0 items-center justify-between"><Heading title="Projects" /><Skeleton className="h-9 w-32" /></div>
    <ProjectCardsSkeleton />
  </div>
}

export function DashboardLoading() { return <OverviewLoading /> }

export function ApiKeysLoading() {
  return <div role="status" aria-label="Loading API keys" className="flex h-[calc(100dvh-6.25rem)] min-h-0 flex-col gap-3 overflow-hidden sm:gap-6 md:h-full">
    <div className="shrink-0"><h1 className="text-2xl font-semibold">API keys</h1><p className="text-xs leading-relaxed text-muted-foreground sm:text-sm">Your own provider keys (OpenAI, Gemini, Anthropic), shared across all your projects.</p></div>
    <Card className="min-h-0 flex-1 gap-3 overflow-hidden py-4 sm:gap-6 sm:py-6">
      <CardHeader className="shrink-0 gap-1.5 px-4 sm:gap-2 sm:px-6"><div className="font-semibold leading-none">Provider API keys</div><p className="text-xs leading-relaxed text-muted-foreground sm:text-sm">Bring your own keys. They&apos;re encrypted at rest and used for this account&apos;s projects. A project can override these with its own key. Prefer not to use a key? Run a local Ollama model instead. <span className="font-medium text-foreground underline underline-offset-4">Key doesn&apos;t work or isn&apos;t supported? Report it.</span></p></CardHeader>
      <div className="min-h-0 overflow-y-auto">
        <div className="hidden grid-cols-[1fr_1fr_5rem] gap-4 border-b px-6 py-3 sm:grid"><Skeleton className="h-4 w-20" /><Skeleton className="h-4 w-12" /></div>
        {Array.from({ length: 8 }, (_, index) => <div key={index} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-b px-4 py-3 last:border-0 sm:grid-cols-[1fr_1fr_5rem] sm:px-6">
          <div className="space-y-2"><Skeleton className="h-4 w-28" /><Skeleton className="h-3 w-36 max-w-full" /></div>
          <Skeleton className="hidden h-3 w-16 sm:block" /><Skeleton className="h-8 w-14 justify-self-end" />
        </div>)}
      </div>
    </Card>
    <Card className="shrink-0 gap-3 py-4 sm:gap-6 sm:py-6">
      <CardHeader className="gap-1.5 px-4 sm:gap-2 sm:px-6"><div className="font-semibold leading-none">Project key overrides</div><p className="text-xs leading-relaxed text-muted-foreground sm:text-sm">Projects that use their own key for a model instead of the account keys above. Manage these in each project&apos;s Settings.</p></CardHeader>
      <div className="max-h-[32dvh] overflow-y-auto sm:max-h-[28dvh]">
        <div className="hidden grid-cols-[1fr_1fr_1fr_5rem] gap-4 border-b px-6 py-3 sm:grid"><Skeleton className="h-4 w-20" /><Skeleton className="h-4 w-24" /><Skeleton className="h-4 w-24" /></div>
        {[0, 1].map(index => <div key={index} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 border-b px-4 py-3 last:border-b-0 sm:grid-cols-[1fr_1fr_1fr_5rem] sm:items-center sm:px-6"><div className="space-y-2"><Skeleton className="h-4 w-32 max-w-full" /><div className="space-y-2 sm:hidden"><Skeleton className="h-3 w-24" /><Skeleton className="h-3 w-36 max-w-full" /><Skeleton className="h-3 w-28" /></div></div><Skeleton className="hidden h-4 w-24 sm:block" /><Skeleton className="hidden h-4 w-24 sm:block" /><Skeleton className="h-8 w-20" /></div>)}
      </div>
    </Card>
  </div>
}

export function ProfileLoading() {
  return <div role="status" aria-label="Loading profile" className="flex flex-col gap-6 overflow-x-hidden md:h-full md:min-h-0 md:overflow-hidden">
    <Heading title="Profile" description="Manage your account, security, sessions and appearance." />
    <div className="space-y-6 md:min-h-0 md:flex-1 md:overflow-y-auto md:pb-1">
      <Card><CardContent className="flex flex-col items-center gap-6 p-6 sm:flex-row sm:items-start sm:gap-8 sm:p-8">
        <Skeleton className="size-24 shrink-0 rounded-full sm:size-28" />
        <div className="w-full min-w-0 flex-1 space-y-4"><div className="max-w-80"><Field /></div><Skeleton className="h-5 w-56 max-w-full" /><div className="flex flex-wrap gap-4"><Skeleton className="h-3 w-32" /><Skeleton className="h-3 w-32" /><Skeleton className="h-3 w-20" /></div></div>
      </CardContent></Card>
      <Card><CardHeader><div className="font-semibold leading-none">Usage overview</div><Skeleton className="h-4 w-3/4" /></CardHeader><CardContent className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[0, 1, 2, 3].map(index => <div key={index} className="space-y-3 rounded-lg border p-4"><Skeleton className="size-5" /><Skeleton className="h-7 w-12" /><Skeleton className="h-3 w-20 max-w-full" /></div>)}</CardContent></Card>
      <Card><CardHeader><Skeleton className="h-4 w-48" /><Skeleton className="h-4 w-3/4" /></CardHeader><CardContent className="space-y-4">{[0, 1].map(index => <div key={index} className="flex items-center justify-between gap-4 rounded-lg border p-4"><div className="w-2/3 space-y-2"><Skeleton className="h-4 w-32" /><Skeleton className="h-3 w-full" /></div><Skeleton className="h-8 w-20" /></div>)}</CardContent></Card>
      <div className="grid gap-6 lg:grid-cols-2">{[0, 1, 2, 3].map(index => <Card key={index}><CardHeader><Skeleton className="h-4 w-32" /><Skeleton className="h-4 w-3/4" /></CardHeader><CardContent className="space-y-4"><Field /><Skeleton className="h-9 w-28" /></CardContent></Card>)}</div>
    </div>
  </div>
}

export function ProjectLoading() {
  return <div role="status" aria-label="Loading project" className="flex h-[calc(100dvh-6.25rem)] min-h-0 flex-col gap-4 overflow-hidden md:h-full md:gap-6">
    <div className="flex shrink-0 flex-wrap items-center gap-3"><Skeleton className="h-8 w-48" /><Skeleton className="h-4 w-96 max-w-full" /></div>
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex h-9 w-full shrink-0 items-center gap-1 rounded-lg bg-muted p-1 md:w-fit">{[48, 64, 80, 36, 64, 64].map((width, index) => <Skeleton key={index} className="h-7 min-w-0 flex-1 md:flex-none" style={{ width }} />)}</div>
      <div className="mt-4 min-h-0 overflow-y-auto rounded-xl border bg-card shadow-sm">
        <div className="flex items-start justify-between gap-3 border-b px-5 py-4"><div className="min-w-0 flex-1 space-y-2"><div className="text-sm font-semibold">Files</div><Skeleton className="h-3 w-60 max-w-full" /></div><Skeleton className="h-8 w-24" /></div>
        <div className="space-y-2 bg-muted/20 p-2 sm:p-3">{[0, 1, 2].map(index => <div key={index} className="flex items-center gap-3 rounded-xl border bg-card p-3 sm:p-4"><Skeleton className="size-11 shrink-0 rounded-xl" /><div className="min-w-0 flex-1 space-y-2"><Skeleton className="h-4 w-1/2" /><Skeleton className="h-3 w-3/4" /></div><Skeleton className="h-7 w-12 rounded-full" /><Skeleton className="size-7 shrink-0" /></div>)}</div>
      </div>
    </div>
  </div>
}

export function NewProjectLoading() {
  return <div role="status" aria-label="Loading new project" className="mx-auto w-full max-w-2xl space-y-6">
    <Heading title="New RAG project" />
    <Card><CardHeader><div className="font-semibold leading-none">1. Name and documents</div><p className="text-sm text-muted-foreground">Give the project a name and upload the files it should know about.</p></CardHeader>
      <CardContent className="space-y-4"><div className="space-y-2"><Field /><Skeleton className="ml-auto h-4 w-8" /></div><Field tall /><div className="space-y-2"><Skeleton className="h-3.5 w-20" /><div className="flex flex-col items-center gap-2 rounded-lg border-2 border-dashed p-8"><Skeleton className="size-6" /><Skeleton className="h-5 w-4/5" /></div></div><div className="flex justify-end gap-2"><Skeleton className="h-9 w-20" /><Skeleton className="h-9 w-24" /></div></CardContent>
    </Card>
  </div>
}

export function ReportKeyIssueLoading() {
  return <div role="status" aria-label="Loading key issue report" className="space-y-6">
    <Heading title="Report a key problem" description="A provider key that fails, isn't accepted, or isn't supported yet? Tell the developer what happened." />
    <Card><CardHeader><div className="font-semibold leading-none">What went wrong?</div><Skeleton className="h-4 w-2/3" /></CardHeader><CardContent className="space-y-4"><div className="space-y-2 rounded-md bg-muted px-3 py-2"><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-3/4" /></div><div className="max-w-52"><Field /></div><div className="space-y-2"><Skeleton className="h-3.5 w-36" /><Skeleton className="h-36 w-full" /></div><div className="flex items-center justify-between gap-4"><Skeleton className="h-4 w-28" /><Skeleton className="h-9 w-36" /></div></CardContent></Card>
  </div>
}
