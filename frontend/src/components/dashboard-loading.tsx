import { Skeleton } from "@/components/ui/skeleton"

function DashboardPageLoading({ title }: { title: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-6" role="status" aria-label={`Loading ${title.toLowerCase()}`}>
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">{title}</h1>
        <Skeleton className="h-4 w-72 max-w-full" />
      </div>
      <Skeleton className="h-48 rounded-xl" />
      <div className="grid gap-4 sm:grid-cols-2">
        <Skeleton className="h-56 rounded-xl" />
        <Skeleton className="h-56 rounded-xl" />
      </div>
    </div>
  )
}

export function DashboardLoading() { return <DashboardPageLoading title="Dashboard" /> }
export function OverviewLoading() { return <DashboardPageLoading title="Overview" /> }
export function ApiKeysLoading() { return <DashboardPageLoading title="API keys" /> }
export function ProfileLoading() { return <DashboardPageLoading title="Profile" /> }
export function ProjectLoading() { return <DashboardPageLoading title="Project" /> }
export function NewProjectLoading() { return <DashboardPageLoading title="New project" /> }
export function ReportKeyIssueLoading() { return <DashboardPageLoading title="Report a key issue" /> }
