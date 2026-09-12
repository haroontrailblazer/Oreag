import { CheckCircleIcon, MinusCircleIcon, XCircleIcon } from "@phosphor-icons/react/dist/ssr"
import { Badge } from "@/components/ui/badge"
import type { EvaluationRun } from "@/lib/evaluation"

export function EvaluationCheckResults({ run }: { run: EvaluationRun }) {
  return <ul className="divide-y rounded-lg border">{run.suite.cases.map(test => {
    const result = run.results.find(result => result.caseId === test.id && result.variant === 0)
    const label = result?.status === "passed" ? "Passed" : result?.status === "failed" ? "Failed" : result?.status === "error" ? "Error" : result?.status === "review" ? "Not checked" : ["preparing", "running"].includes(run.status) ? "Pending" : "Not run"
    const Icon = label === "Passed" ? CheckCircleIcon : label === "Failed" || label === "Error" ? XCircleIcon : MinusCircleIcon
    const change = run.quality_report?.case_changes?.find(item => item.case_id === test.id)
    return <li key={test.id} className="space-y-2 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2"><p className="min-w-0 flex-1 text-xs font-medium leading-5 [overflow-wrap:anywhere]">{test.question}</p><Badge variant="outline" className={label === "Passed" ? "text-emerald-700 dark:text-emerald-400" : label === "Failed" ? "text-red-700 dark:text-red-400" : "text-muted-foreground"}><Icon aria-hidden="true" />{label}</Badge></div>
      {change && <p className="text-[11px] text-muted-foreground">{change.before === change.after ? "Check result unchanged" : change.before === "failed" && change.after === "passed" ? "Previously failed; now passing" : change.before === "passed" && change.after === "failed" ? "Previously passed; now failing" : "Check status changed"}</p>}
      {result?.response && <details className="text-xs"><summary className="w-fit cursor-pointer rounded-sm text-muted-foreground focus-visible:outline-2">Answer and checks</summary><div className="mt-2 space-y-2 leading-5 [overflow-wrap:anywhere]"><p className="whitespace-pre-wrap">{result.response.answer || "No answer text returned."}</p><p className="text-muted-foreground">{test.expected ? `${test.match === "exact" ? "Exact answer" : "Answer contains"}: ${test.expected}` : "No answer-text check"}</p><p className="text-muted-foreground">{test.source ? `Expected source: ${test.source}` : "No source check"}</p><p className="text-muted-foreground">Returned sources: {result.response.sources.map(source => source.filename).filter(Boolean).join(", ") || "None"}</p></div></details>}
    </li>
  })}</ul>
}
