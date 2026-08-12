import { UsageView } from "@/components/settings/usage-dashboard"
import type { AccountUsage } from "@/lib/types"

const fixture: AccountUsage = {
  window_days: 30,
  totals: {
    requests: 1284,
    prompt_tokens: 2840000,
    completion_tokens: 486000,
    cost_usd: 42.86,
    saved_prompt_tokens: 1460000,
    saved_completion_tokens: 242000,
    saved_cost_usd: 18.74,
    embedding_tokens: 12800000,
    embedding_cost_usd: 8.42,
    saved_embedding_tokens: 3200000,
    saved_embedding_cost_usd: 2.18,
  },
  by_model: [
    {
      model: "gpt-4o-mini",
      requests: 684,
      prompt_tokens: 1_520_000,
      completion_tokens: 248_000,
      cost_usd: 21.74,
      kind: "llm",
    },
    {
      model: "gpt-4.1-mini",
      requests: 412,
      prompt_tokens: 1_120_000,
      completion_tokens: 198_000,
      cost_usd: 17.92,
      kind: "llm",
    },
    {
      model: "text-embedding-3-large",
      requests: 188,
      prompt_tokens: 12_800_000,
      completion_tokens: null,
      cost_usd: 8.42,
      kind: "embedding",
    },
  ],
  by_endpoint: [
    { endpoint: "query", requests: 412, prompt_tokens: 1_840_000,
      completion_tokens: 262_000, embedding_tokens: 96_000, cost_usd: 24.1,
      p50_latency_ms: 1840 },
    { endpoint: "memory_create", requests: 268, prompt_tokens: null,
      completion_tokens: null, embedding_tokens: 412_000, cost_usd: 0.31,
      p50_latency_ms: 240 },
    { endpoint: "file_ingest", requests: 96, prompt_tokens: null,
      completion_tokens: null, embedding_tokens: 8_400_000, cost_usd: 5.6,
      p50_latency_ms: 18_400 },
  ],
  by_api_key: [
    {
      api_key_id: "production",
      key_prefix: "oreag_live_8f4a",
      revoked: false,
      requests: 842,
      prompt_tokens: 1_920_000,
      completion_tokens: 318_000,
      cost_usd: 31.86,
    },
    {
      api_key_id: "analytics",
      key_prefix: "oreag_live_c12e",
      revoked: false,
      requests: 326,
      prompt_tokens: 720_000,
      completion_tokens: 128_000,
      cost_usd: 14.18,
    },
    {
      api_key_id: "legacy",
      key_prefix: "oreag_test_a093",
      revoked: true,
      requests: 116,
      prompt_tokens: null,
      completion_tokens: null,
      cost_usd: null,
    },
  ],
  by_project: [
    {
      project_id: "support",
      name: "Customer Support Knowledge",
      requests: 612,
      cost_usd: 22.8,
      cache: { l1: 142, l2: 126, miss: 344, hit_rate: 0.438 },
      avg_retrieval_similarity: 0.78,
      avg_cache_similarity: 0.91,
      saved_prompt_tokens: 820_000,
      saved_completion_tokens: 132_000,
    },
    {
      project_id: "research",
      name: "Research Workspace",
      requests: 438,
      cost_usd: 18.34,
      cache: { l1: 86, l2: 94, miss: 258, hit_rate: 0.411 },
      avg_retrieval_similarity: 0.74,
      avg_cache_similarity: 0.88,
      saved_prompt_tokens: 496_000,
      saved_completion_tokens: 82_000,
    },
    {
      project_id: "internal",
      name: "Internal Operations",
      requests: 234,
      cost_usd: 10.14,
      cache: { l1: 54, l2: 48, miss: 132, hit_rate: 0.436 },
      avg_retrieval_similarity: null,
      avg_cache_similarity: null,
      saved_prompt_tokens: 144_000,
      saved_completion_tokens: 28_000,
    },
  ],
  daily: Array.from({ length: 14 }, (_, index) => ({
    date: `2026-07-${String(index + 15).padStart(2, "0")}`,
    requests: 42 + index * 7,
    prompt_tokens: 72000 + index * 9400,
    completion_tokens: 13000 + index * 1200,
    cost_usd: 1.1 + index * 0.18,
    saved_prompt_tokens: 33000 + index * 5200,
    embedding_tokens: 280000 + index * 53000,
    embedding_cost_usd: 0.24 + index * 0.04,
    p50_latency_ms: 620 + index * 40,
    p95_latency_ms: 3100 + index * 260,
    p99_latency_ms: 7400 + index * 520,
    cache_l1: 3 + (index % 5),
    cache_l2: 6 + (index % 7),
    cache_miss: 12 + (index % 4),
    avg_retrieval_similarity: 0.51 + (index % 6) * 0.012,
  })),
  caveats: {
    unmeasured_requests: 0,
    unmeasured_models: [],
    vision_and_audio_excluded: false,
  },
}

export default function UsagePreviewPage() {
  return (
    <main className="usage-dashboard min-h-screen bg-background p-4 sm:p-6 lg:p-8">
      <div className="mx-auto flex max-w-[1480px] flex-col gap-6">
        <div className="usage-dashboard-header flex items-center justify-between border-b border-border/70 pb-5">
          <div>
          <h1 className="text-[1.75rem] font-semibold leading-tight tracking-[-0.035em]">Usage</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Requests, tokens and cost across your API keys, models and projects.
          </p>
          </div>
          <div className="hidden rounded-xl border border-border/80 bg-muted/60 p-1 text-xs font-semibold shadow-sm sm:flex">
            <span className="rounded-lg px-3.5 py-2 text-muted-foreground">7 days</span>
            <span className="rounded-lg bg-background px-3.5 py-2 text-foreground shadow-sm">30 days</span>
            <span className="rounded-lg px-3.5 py-2 text-muted-foreground">90 days</span>
          </div>
        </div>
        <UsageView data={fixture} />
      </div>
    </main>
  )
}
