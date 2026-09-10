"use client"

import { FilterSelect } from "@/components/filter-select"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { dimensionOptions, isDeprecated, providerUsable } from "@/lib/models"
import type { EvaluationConfig } from "@/lib/evaluation"
import type { ModelsResponse, Project } from "@/lib/types"

export function EvaluationConfigCard({ value, onChange, index, models, project }: {
  value: EvaluationConfig; onChange: (next: EvaluationConfig) => void; index: number; models: ModelsResponse; project: Project
}) {
  const label = index === 0 ? "A · Baseline" : "B · Challenger"
  const update = (patch: Partial<EvaluationConfig>) => onChange({ ...value, ...patch })
  const llms = Object.entries(models.catalog.llm).flatMap(([provider, entries]) =>
    providerUsable(provider, "llm", models.availability, project) ? entries.filter(model => !isDeprecated(models, "llm", provider, model)).map(model => ({ value: `${provider}/${model}`, label: `${provider} / ${model}` })) : [])
  const embedders = Object.entries(models.catalog.embedding).flatMap(([provider, entries]) =>
    providerUsable(provider, "embedding", models.availability, project) ? entries.filter(entry => !isDeprecated(models, "embedding", provider, entry.model)).map(entry => ({ value: `${provider}/${entry.model}`, label: `${provider} / ${entry.model}` })) : [])
  function withCurrent(options: { value: string; label: string }[], current: string) {
    return options.some(o => o.value === current) ? options : [{ value: current, label: `${current} (unavailable)` }, ...options]
  }
  const embedding = models.catalog.embedding[value.embedding_provider]?.find(entry => entry.model === value.embedding_model)
  const dimensions = embedding ? dimensionOptions(embedding) : [value.embedding_dimensions]
  return <section className="min-w-0 rounded-xl border bg-card">
    <div className="flex items-center gap-2 border-b px-4 py-3"><span className="flex size-6 items-center justify-center rounded-md bg-muted text-xs font-semibold">{index === 0 ? "A" : "B"}</span><h3 className="text-sm font-medium">{index === 0 ? "Baseline" : "Challenger"}</h3></div>
    <div className="space-y-4 p-4">
      <FilterSelect label="Answer model" ariaLabel={`${label} answer model`} value={`${value.llm_provider}/${value.llm_model}`} options={withCurrent(llms, `${value.llm_provider}/${value.llm_model}`)} onChange={model => { const slash = model.indexOf("/"); update({ llm_provider: model.slice(0, slash), llm_model: model.slice(slash + 1) }) }} />
      <FilterSelect label="Embedding model" ariaLabel={`${label} embedding model`} value={`${value.embedding_provider}/${value.embedding_model}`} options={withCurrent(embedders, `${value.embedding_provider}/${value.embedding_model}`)} onChange={model => {
        const slash = model.indexOf("/"), provider = model.slice(0, slash), name = model.slice(slash + 1)
        const entry = models.catalog.embedding[provider].find(e => e.model === name)!
        update({ embedding_provider: provider, embedding_model: name, embedding_dimensions: entry.dimensions })
      }} />
      <div className="grid grid-cols-2 items-end gap-3">
        <FilterSelect label="Vector dimensions" ariaLabel={`${label} vector dimensions`} value={String(value.embedding_dimensions)} options={dimensions.map(d => ({ value: String(d), label: String(d) }))} onChange={v => update({ embedding_dimensions: Number(v) })} />
        <FilterSelect label="Top-K" ariaLabel={`${label} top_k`} value={String(value.top_k)} options={Array.from({ length: 20 }, (_, n) => ({ value: String(n + 1), label: `${n + 1} chunks` }))} onChange={v => update({ top_k: Number(v) })} />
      </div>
      <details className="border-t pt-3"><summary className="cursor-pointer text-xs font-medium">Retrieval and answer policy</summary>
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <label className="space-y-1.5 text-xs">Minimum similarity<Input aria-label={`${label} minimum similarity`} type="number" min={0} max={1} step={0.05} value={value.min_similarity} onChange={e => update({ min_similarity: Number(e.target.value) })} /></label>
            <label className="space-y-1.5 text-xs">Strong sources<Input aria-label={`${label} strong sources`} type="number" min={0} max={20} value={value.min_strong} onChange={e => update({ min_strong: Number(e.target.value) })} /></label>
          </div>
          <label className="block space-y-1.5 text-xs">Translation similarity floor<Input aria-label={`${label} translation floor`} type="number" min={0} max={1} step={0.05} placeholder="Automatic" value={value.cross_lingual_floor ?? ""} onChange={e => update({ cross_lingual_floor: e.target.value === "" ? null : Number(e.target.value) })} /></label>
          <label className="flex gap-2 text-xs"><input type="checkbox" className="accent-foreground" checked={value.hybrid_search} onChange={e => update({ hybrid_search: e.target.checked })} />Hybrid keyword + semantic search</label>
          <label className="flex gap-2 text-xs"><input type="checkbox" className="accent-foreground" checked={value.include_memories} onChange={e => update({ include_memories: e.target.checked })} />Include indexed memories</label>
          <label className="block space-y-1.5 text-xs">Document language<Input aria-label={`${label} document language`} maxLength={100} placeholder="English (default)" value={value.document_language ?? ""} onChange={e => update({ document_language: e.target.value || null })} /></label>
          <label className="block space-y-1.5 text-xs">Answer language<Input aria-label={`${label} answer language`} maxLength={100} placeholder="Follow the question" value={value.answer_language ?? ""} onChange={e => update({ answer_language: e.target.value || null })} /></label>
          <label className="flex gap-2 text-xs"><input type="checkbox" className="accent-foreground" checked={value.answer_language_strict} onChange={e => update({ answer_language_strict: e.target.checked })} />Always use the selected answer language</label>
          <label className="block space-y-1.5 text-xs">Answer notice<Textarea aria-label={`${label} answer notice`} maxLength={2000} placeholder="Optional notice appended to answers" value={value.answer_disclaimer ?? ""} onChange={e => update({ answer_disclaimer: e.target.value || null })} /></label>
        </div>
      </details>
    </div>
  </section>
}
