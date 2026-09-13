"use client"

import { useState } from "react"
import useSWR from "swr"
import { ArrowsClockwiseIcon, FlaskIcon } from "@phosphor-icons/react/dist/ssr"
import { fetcher, isSessionExpired } from "@/lib/api"
import type { EvaluationRun } from "@/lib/evaluation"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { FilterSelect } from "@/components/filter-select"
import { EvaluationCheckResults } from "@/components/evaluation-check-results"

export function ChangeChecks({ base }: { base: string }) {
  const { data, error, mutate } = useSWR<EvaluationRun[]>(`${base}/change-checks`, fetcher, { refreshInterval: value => value?.some(run => ["preparing", "running"].includes(run.status)) ? 3000 : 30000 })
  const [selection, setSelection] = useState("")
  const run = data?.find(run => run.id === selection) ?? data?.[0]
  return <Card role="region" aria-label="Checks after changes" className="min-w-0 gap-5">
    <CardHeader>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <CardTitle role="heading" aria-level={3} className="flex items-center gap-2 text-sm"><FlaskIcon className="size-4 text-muted-foreground" aria-hidden="true" />Checks after changes</CardTitle>
        <Button size="icon-sm" variant="ghost" title="Refresh results" aria-label="Refresh change check results" onClick={() => void mutate()}><ArrowsClockwiseIcon aria-hidden="true" /></Button>
      </div>
      <CardDescription className="text-xs leading-5">Results from saved questions checked after document, memory, or answer-setting changes.</CardDescription>
    </CardHeader>
    <CardContent className="min-w-0 space-y-4">
      {error && !isSessionExpired(error) ? <div role="alert" className="space-y-2 text-xs"><p>Could not load change checks.</p><Button size="sm" variant="outline" onClick={() => void mutate()}>Retry</Button></div> : !run ? <p className="text-xs text-muted-foreground">{data ? "No checks after changes yet." : "Loading checks…"}</p> : <>
        {data && data.length > 1 && <FilterSelect label="Check run" value={run.id} onChange={setSelection} options={data.map(item => ({ value: item.id, label: `${new Date(item.created_at).toLocaleString()} · ${item.status}` }))} />}
        <div className="space-y-2 rounded-lg bg-muted/40 p-3"><div className="flex flex-wrap items-center gap-2">{run.status === "completed" ? <><Badge variant="outline">{run.results.filter(row => row.status === "passed").length} passed</Badge><Badge variant="outline">{run.results.filter(row => row.status === "failed").length} failed</Badge><Badge variant="outline">{run.results.filter(row => row.status === "review").length} not checked</Badge></> : <Badge variant="outline" className="capitalize">{run.status}</Badge>}</div><p className="text-xs text-muted-foreground">{new Date(run.created_at).toLocaleString()}</p></div>
        {run.error && <p role="alert" className="text-xs text-destructive">{run.error}</p>}
        {run.quality_report?.configuration_changed && <p className="text-xs leading-5 text-muted-foreground">Project settings changed between these runs. Results show the observed difference across both configurations.</p>}
        {run.status === "completed" && !run.quality_report?.case_changes && <p className="text-xs leading-5 text-muted-foreground">No comparable earlier check is available for these questions.</p>}
        <div role="region" aria-label="Question check results" tabIndex={0} className="max-h-[28rem] overflow-y-auto rounded-lg focus-visible:outline-2 focus-visible:outline-ring"><EvaluationCheckResults run={run} /></div>
      </>}
      {!error && !run && (data ? <div className="flex min-h-40 flex-col items-center justify-center gap-3 rounded-lg border border-dashed px-5 py-6 text-center"><FlaskIcon aria-hidden="true" className="size-7 text-muted-foreground" /><p className="max-w-sm text-xs leading-5 text-muted-foreground">Enable Run after changes in Automatic checks to test your saved questions when the project changes. Completed checks will appear here.</p></div> : <div role="status" aria-label="Loading change check results" className="space-y-3"><Skeleton className="h-16 rounded-lg" /><Skeleton className="h-24 rounded-lg" /></div>)}
      <p className="border-t pt-4 text-xs leading-5 text-muted-foreground">Uses the project’s current settings. Configure triggers in Project settings → Automatic checks.</p>
    </CardContent>
  </Card>
}
