"use client"

import { useState } from "react"
import useSWR from "swr"
import { ArrowsClockwiseIcon, FlaskIcon } from "@phosphor-icons/react/dist/ssr"
import { fetcher, isSessionExpired } from "@/lib/api"
import type { EvaluationRun } from "@/lib/evaluation"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { EvaluationCheckResults } from "@/components/evaluation-check-results"

export function ChangeChecks({ base }: { base: string }) {
  const { data, error, mutate } = useSWR<EvaluationRun[]>(`${base}/change-checks`, fetcher, { refreshInterval: value => value?.some(run => ["preparing", "running"].includes(run.status)) ? 3000 : 30000 })
  const [selection, setSelection] = useState("")
  const run = data?.find(run => run.id === selection) ?? data?.[0]
  return <details className="rounded-xl border bg-card p-4">
    <summary className="cursor-pointer rounded-sm text-sm font-medium focus-visible:outline-2"><span className="inline-flex items-center gap-2"><FlaskIcon className="size-4 text-muted-foreground" aria-hidden="true" />Checks after changes</span>{run && <span className="ml-2 text-xs font-normal text-muted-foreground">{run.status === "completed" ? "Results available" : run.status}</span>}</summary>
    <div className="mt-4 space-y-3">
      <p className="text-xs leading-5 text-muted-foreground">Uses the saved questions with the project’s current settings after document, memory, or answer-setting changes. Configure this in Project settings → Automatic checks.</p>
      {error && !isSessionExpired(error) ? <div role="alert" className="space-y-2 text-xs"><p>Could not load change checks.</p><Button size="sm" variant="outline" onClick={() => void mutate()}>Retry</Button></div> : !run ? <p className="text-xs text-muted-foreground">{data ? "No checks after changes yet." : "Loading checks…"}</p> : <>
        <div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{run.status === "completed" ? `${run.results.filter(row => row.status === "passed").length} passed · ${run.results.filter(row => row.status === "failed").length} failed · ${run.results.filter(row => row.status === "review").length} not checked` : run.status}</Badge><span className="text-[11px] text-muted-foreground">{new Date(run.created_at).toLocaleString()}</span></div>
        {run.error && <p role="alert" className="text-xs text-destructive">{run.error}</p>}
        {run.quality_report?.configuration_changed && <p className="text-xs leading-5 text-muted-foreground">Project settings changed between these runs. Results show the observed difference across both configurations.</p>}
        {run.status === "completed" && !run.quality_report?.case_changes && <p className="text-xs leading-5 text-muted-foreground">No comparable earlier check is available for these questions.</p>}
        <EvaluationCheckResults run={run} />
        {data && data.length > 1 && <div className="flex flex-wrap gap-2">{data.map(item => <Button key={item.id} variant="outline" size="sm" onClick={() => setSelection(item.id)}>{new Date(item.created_at).toLocaleString()}</Button>)}</div>}
      </>}
      <Button size="sm" variant="ghost" onClick={() => void mutate()}><ArrowsClockwiseIcon aria-hidden="true" />Refresh results</Button>
    </div>
  </details>
}
