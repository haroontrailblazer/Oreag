import { DatabaseIcon } from "@phosphor-icons/react/dist/ssr"
import { Badge } from "@/components/ui/badge"
import type { QueryRecord } from "@/lib/query-explorer"

const reasons: Record<string, string> = {
  hit: "A reusable answer was found.", no_entry: "No matching, unexpired entry was available.",
  unavailable: "The cache could not be read, so this layer was skipped.",
  unreadable: "The stored entry could not be read and was skipped.", disabled: "This cache layer was disabled.",
  context_unavailable: "Conversation history could not be read, so cache reuse was bypassed.",
  bypassed: "This request explicitly bypassed the answer cache.", conversation_context: "Semantic reuse was skipped because this question has conversation history. Exact caching includes that history.",
  exact_hit: "Skipped because the exact cache supplied the answer.", below_threshold: "The closest cached question did not meet the similarity threshold.",
  different_request: "Similar wording was found, but the request was not equivalent. A fresh answer preserves the requested intent.",
  unusable_answer: "The matching entry had no reusable answer.", embedding_unavailable: "The question could not be embedded for a semantic lookup.",
  not_checked: "A cache decision was not recorded for this layer.",
}

export function CacheInspector({ query }: { query: QueryRecord }) {
  const details = query.cache_details
  return <section className="space-y-3 rounded-xl border p-4" aria-label="Cache inspector">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="flex items-center gap-2 text-sm font-medium"><DatabaseIcon className="size-4 text-muted-foreground" aria-hidden="true" />Cache inspector</h3>{details && <Badge variant="outline">{query.cache_layer === "l1" ? "Exact hit" : query.cache_layer === "l2" ? "Semantic hit" : "Fresh answer"}</Badge>}</div>
    {!details ? <p className="text-xs leading-5 text-muted-foreground">Cache decisions were not recorded for this query. New queries include the lookup details.</p> : <>
      <dl className="space-y-3 text-xs">{[["Exact cache", details.exact], ["Semantic cache", details.semantic]].map(([label, reason]) => <div key={label} className="space-y-1"><dt className="font-medium">{label}</dt><dd className="leading-5 text-muted-foreground">{reasons[reason] ?? "Decision not recorded."}</dd></div>)}</dl>
      <details className="text-xs"><summary className="w-fit cursor-pointer rounded-sm font-medium focus-visible:outline-2">Request context</summary><div className="mt-2 space-y-2 leading-5 text-muted-foreground"><p>{details.exact_backend === "redis" ? "Redis exact cache" : "In-memory exact cache"} · {details.conversation_turns} prior {details.conversation_turns === 1 ? "turn" : "turns"}{details.content_version != null ? ` · Content version ${details.content_version}` : ""}</p><p>Reuse requires matching project settings, documents, and conversation context.{details.exact_ttl_seconds != null ? ` Exact entries are configured to expire after ${details.exact_ttl_seconds} seconds.` : ""}</p><p>A missing entry alone does not reveal whether it expired or was never stored.</p></div></details>
    </>}
  </section>
}
