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
  by_model: [],
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
  by_api_key: [],
  by_project: [],
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
    <main className="min-h-screen bg-background p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <div>
          <h1 className="text-2xl font-semibold">Usage</h1>
          <p className="text-sm text-muted-foreground">
            Requests, tokens and cost across your API keys, models and projects.
          </p>
        </div>
        <UsageView data={fixture} />
      </div>
    </main>
  )
}
