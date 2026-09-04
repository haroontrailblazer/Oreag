"use client"

import {
  ChatCircleIcon as ChatCircle,
  CubeIcon as Cube,
  GaugeIcon as Gauge,
  ScalesIcon as Scales,
  GearSixIcon as GearSix,
  WarningOctagonIcon as WarningOctagon,
} from "@phosphor-icons/react/dist/ssr"
import { useRouter } from "next/navigation"
import { useRef, useState } from "react"
import { toast } from "@/lib/toast"
import useSWR, { mutate as globalMutate } from "swr"

import { ProviderKeyField } from "@/components/project/provider-key-field"
import { BestPractices } from "@/components/ui/best-practices"
import { BoxLoader } from "@/components/ui/box-loader"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { EncryptingLoader } from "@/components/ui/encrypting-loader"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Spin } from "@/components/ui/loader"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { api, fetcher } from "@/lib/api"
import {
  CostViz,
  DimensionsViz,
  GroundingViz,
  KeyViz,
  OverrideViz,
  TopKViz,
  TranslateViz,
} from "@/components/ui/best-practice-visuals"
import {
  dimensionOptions,
  isDeprecated,
  providerOf,
  providerUsable,
} from "@/lib/models"
import { cn } from "@/lib/utils"
import type { ModelsResponse, Project } from "@/lib/types"

// Radix Select cannot hold "" as an item value, and "" is what the API means
// by "mirror each question". A sentinel stands in for it in the widget only -
// what gets saved is still "" or a language name.
const MATCH_QUESTION = "__match__"

// The stored value is interpolated straight into the model's instruction
// ("write the entire answer in X"), so these are plain language names rather
// than locale codes - "Portuguese (Brazil)" reads correctly to a model,
// "pt-BR" does not.
//
// EVERY ENTRY IS VERIFIED, not assumed. Each was run end to end through the
// product's own prompt - English sources, English question, this language
// pinned - and kept only when the answer came back in the right writing
// system, was identified as that language, and still carried the fact from
// the source. 39 of the 40 candidates passed.
//
// Malay is why one entry carries its endonym. Asked for "Malay" the model
// returned INDONESIAN three times out of three ("pengajuan", "lewat"), and a
// judge told to choose between the two called it Indonesian every time.
// Asked for "Malay (Bahasa Melayu)" it returned Malay three times out of
// three. The parenthetical is load-bearing, not decoration - do not tidy it
// away. Re-measure before adding anything here.
const ANSWER_LANGUAGES = [
  "Arabic", "Bengali", "Burmese", "Chinese (Simplified)",
  "Chinese (Traditional)", "Dutch", "English", "French", "German", "Gujarati",
  "Hebrew", "Hindi", "Indonesian", "Italian", "Japanese", "Kannada", "Khmer",
  "Korean", "Lao", "Malay (Bahasa Melayu)", "Malayalam", "Marathi", "Nepali",
  "Odia", "Persian", "Polish", "Portuguese", "Portuguese (Brazil)", "Punjabi",
  "Russian", "Sinhala", "Spanish", "Swahili", "Tamil", "Telugu", "Thai",
  "Turkish", "Ukrainian", "Urdu", "Vietnamese",
]

// Languages whose DOCUMENTS Oreag can stem for keyword search (migration
// 0039). A different list from ANSWER_LANGUAGES above, and deliberately much
// shorter: every entry here changes how the search index is built, and a
// language Postgres has no stemmer for would be an option that silently does
// nothing. Offering those would be worse than leaving them out.
//
// The first group was MEASURED - a query word in a different grammatical form
// finds the document under this language's stemmer and does not under
// English. The second group has a stemmer built for the language, which beats
// one built for English, but the test pair did not demonstrate it.
const DOCUMENT_LANGUAGES = [
  "Arabic", "Armenian", "Basque", "Catalan", "Danish", "Dutch", "English",
  "Finnish", "French", "German", "Greek", "Hindi", "Hungarian", "Indonesian",
  "Irish", "Italian", "Lithuanian", "Nepali", "Norwegian", "Portuguese",
  "Portuguese (Brazil)", "Romanian", "Russian", "Serbian", "Spanish",
  "Swedish", "Tamil", "Turkish", "Yiddish",
]

export function SettingsTab({
  project,
  onChanged,
}: {
  project: Project
  onChanged: () => void
}) {
  const router = useRouter()
  const { data: models } = useSWR<ModelsResponse>("/api/models", fetcher)
  const availability = models?.availability ?? { openai: true }

  // General
  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? "")
  const [topK, setTopK] = useState(project.top_k)
  const [saving, setSaving] = useState(false)

  // Answer model (LLM) - instant save
  const [llm, setLlm] = useState(`${project.llm_provider}/${project.llm_model}`)
  const [llmKeyInput, setLlmKeyInput] = useState("")
  const [llmEditingKey, setLlmEditingKey] = useState(false)
  const [savingLlm, setSavingLlm] = useState(false)
  // True only while a NEW key is being encrypted + stored (drives the
  // encrypting animation; plain model changes keep the quiet button spinner).
  const [encryptingLlm, setEncryptingLlm] = useState(false)

  // Indexing + embedding - key-only change is instant; model/chunk change re-indexes
  const [chunkSize, setChunkSize] = useState(project.chunk_size)
  const [chunkOverlap, setChunkOverlap] = useState(project.chunk_overlap)
  const [embedding, setEmbedding] = useState(
    `${project.embedding_provider}/${project.embedding_model}`
  )
  const [embDimensions, setEmbDimensions] = useState(project.embedding_dimensions)
  const [embKeyInput, setEmbKeyInput] = useState("")
  const [embEditingKey, setEmbEditingKey] = useState(false)
  const [savingEmbKey, setSavingEmbKey] = useState(false)
  const [encryptingEmb, setEncryptingEmb] = useState(false)
  const [confirmReindex, setConfirmReindex] = useState(false)
  const [reindexing, setReindexing] = useState(false)

  // Answer policy (0032). Held as strings so the inputs stay editable while
  // half-typed ("0." is not a number yet); parsed once, on save.
  const [minSimilarity, setMinSimilarity] = useState(String(project.min_similarity))
  const [minStrong, setMinStrong] = useState(String(project.min_strong))
  const [answerLanguage, setAnswerLanguage] = useState(project.answer_language ?? "")
  const [answerDisclaimer, setAnswerDisclaimer] = useState(
    project.answer_disclaimer ?? ""
  )
  const [documentLanguage, setDocumentLanguage] = useState(
    project.document_language ?? ""
  )
  const [languageStrict, setLanguageStrict] = useState(
    project.answer_language_strict ?? true
  )
  const [savingPolicy, setSavingPolicy] = useState(false)
  const [versionTracking, setVersionTracking] = useState(project.version_tracking)

  // Re-sync the form when the PROJECT changes underneath it.
  //
  // Every field above is a useState seeded once, at mount - and this tab is
  // force-mounted 150ms after the page loads, whether or not it is ever opened.
  // Meanwhile the project can be rewritten from elsewhere: the Playground's
  // model dropdown PATCHes llm_provider/llm_model project-wide, and a re-index
  // rewrites the embedding config. Without this, the tab kept rendering
  // page-load values, so the Overview card and the input directly beneath it
  // showed different numbers - and pressing Save wrote the stale value back,
  // silently reverting the change made elsewhere.
  //
  // A THREE-WAY MERGE, not a reset. A field is adopted only when the local
  // value still equals what the server last told us; if the user has edited it,
  // their edit wins and is left untouched. A blunt reset would wipe whatever
  // someone was halfway through typing every time the project list revalidated
  // - which, while a file is indexing, is every 3 seconds.
  //
  // Adjusted during render (same pattern as projects/[id]/page.tsx:56) rather
  // than in an effect: an effect would render the stale value first, then
  // correct it, which is a visible flicker. Remounting via a changing `key`
  // was the other option and is worse - it refetches everything and destroys
  // in-progress edits unconditionally.
  const modelValue = (provider: string, model: string) => `${provider}/${model}`
  const [synced, setSynced] = useState(project)
  if (project !== synced) {
    setSynced(project)
    setName((v) => (v === synced.name ? project.name : v))
    setDescription((v) =>
      v === (synced.description ?? "") ? project.description ?? "" : v
    )
    setTopK((v) => (v === synced.top_k ? project.top_k : v))
    setLlm((v) =>
      v === modelValue(synced.llm_provider, synced.llm_model)
        ? modelValue(project.llm_provider, project.llm_model)
        : v
    )
    setChunkSize((v) => (v === synced.chunk_size ? project.chunk_size : v))
    setChunkOverlap((v) =>
      v === synced.chunk_overlap ? project.chunk_overlap : v
    )
    setEmbedding((v) =>
      v === modelValue(synced.embedding_provider, synced.embedding_model)
        ? modelValue(project.embedding_provider, project.embedding_model)
        : v
    )
    setEmbDimensions((v) =>
      v === synced.embedding_dimensions ? project.embedding_dimensions : v
    )
    setMinSimilarity((v) =>
      v === String(synced.min_similarity) ? String(project.min_similarity) : v
    )
    setMinStrong((v) =>
      v === String(synced.min_strong) ? String(project.min_strong) : v
    )
    setAnswerLanguage((v) =>
      v === (synced.answer_language ?? "") ? project.answer_language ?? "" : v
    )
    setAnswerDisclaimer((v) =>
      v === (synced.answer_disclaimer ?? "")
        ? project.answer_disclaimer ?? ""
        : v
    )
    setDocumentLanguage((v) =>
      v === (synced.document_language ?? "") ? project.document_language ?? "" : v
    )
    setLanguageStrict((v) =>
      v === (synced.answer_language_strict ?? true)
        ? project.answer_language_strict ?? true
        : v
    )
    setVersionTracking((v) =>
      v === synced.version_tracking ? project.version_tracking : v
    )
  }

  const [confirmSuspend, setConfirmSuspend] = useState(false)
  const [suspending, setSuspending] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const deleteDone = useRef(false)

  // --- LLM derived state -----------------------------------------------------
  const llmProvider = providerOf(llm)
  const llmAccountHasKey = Boolean(availability[llmProvider])
  const llmOverrideLast4 =
    project.llm_provider === llmProvider ? project.llm_key_last4 : null
  const llmUsable =
    llmAccountHasKey || Boolean(llmOverrideLast4) || Boolean(llmKeyInput.trim())
  const llmChanged = llm !== `${project.llm_provider}/${project.llm_model}`
  const canSaveLlm = (llmChanged || Boolean(llmKeyInput.trim())) && llmUsable
  // No account key and no override → the input is shown unconditionally.
  const llmForcedInput = !llmAccountHasKey && !llmOverrideLast4

  // --- Embedding derived state ----------------------------------------------
  const embProvider = providerOf(embedding)
  const embAccountHasKey = Boolean(availability[embProvider])
  const embOverrideLast4 =
    project.embedding_provider === embProvider
      ? project.embedding_key_last4
      : null
  const embUsable =
    embAccountHasKey || Boolean(embOverrideLast4) || Boolean(embKeyInput.trim())
  const embModelChanged =
    embedding !== `${project.embedding_provider}/${project.embedding_model}`
  const chunkChanged =
    chunkSize !== project.chunk_size || chunkOverlap !== project.chunk_overlap
  const embEntry = models?.catalog.embedding[embProvider]?.find(
    (entry) => `${embProvider}/${entry.model}` === embedding
  )
  const embDimOptions = embEntry ? dimensionOptions(embEntry) : [embDimensions]
  const embDimsChanged = embDimensions !== project.embedding_dimensions
  // Same MRL model at a smaller size: the backend cuts the stored vectors to
  // the prefix in place, banking the wider original - instant, nothing is
  // re-embedded, and reversible.
  const instantShrink =
    !embModelChanged &&
    !chunkChanged &&
    embDimsChanged &&
    embDimensions < project.embedding_dimensions
  // Growing BACK up to a width already archived by an earlier shrink. Also
  // instant: the originals are restored from the archive rather than
  // recomputed. Anything wider than the archive really does need re-embedding,
  // which is why this is capped at embedding_native_dimensions rather than
  // being true for every grow.
  const instantRestore =
    !embModelChanged &&
    !chunkChanged &&
    embDimsChanged &&
    embDimensions > project.embedding_dimensions &&
    embDimensions <= (project.embedding_native_dimensions ?? 0)
  const instantChange = instantShrink || instantRestore
  const reindexNeeded = embModelChanged || chunkChanged || embDimsChanged
  const embKeyOnly = !reindexNeeded && Boolean(embKeyInput.trim())
  const embForcedInput = !embAccountHasKey && !embOverrideLast4
  // With no files there is nothing to re-index - a model/chunk change just
  // saves config, so drop the re-index confirmation and its "N files" wording.
  const hasFiles = project.file_count > 0
  // The currently-selected models' providers may have lost their key - grey
  // them so a stale model doesn't look usable.
  const llmCurrentUsable = providerUsable(llmProvider, "llm", availability, project)
  const embCurrentUsable = providerUsable(
    embProvider,
    "embedding",
    availability,
    project
  )

  function changeLlm(value: string) {
    setLlm(value)
    setLlmKeyInput("")
    setLlmEditingKey(false)
  }

  function changeEmbedding(value: string) {
    setEmbedding(value)
    const [prov, mod] = value.split("/", 2)
    // Back to the project's model -> its saved size; otherwise the new
    // model's default size.
    if (prov === project.embedding_provider && mod === project.embedding_model) {
      setEmbDimensions(project.embedding_dimensions)
    } else {
      const entry = models?.catalog.embedding[prov]?.find((e) => e.model === mod)
      setEmbDimensions(entry?.dimensions ?? project.embedding_dimensions)
    }
    setEmbKeyInput("")
    setEmbEditingKey(false)
  }

  async function handleSave() {
    setSaving(true)
    try {
      await api(`/api/projects/${project.id}`, {
        method: "PATCH",
        // Empty string - not null - is how "clear the description" travels:
        // ProjectUpdate treats null as "field omitted, leave it alone", so a
        // null here would silently no-op the one edit the user meant to make.
        // The router normalises blank back to NULL on the way in.
        body: JSON.stringify({ name, description: description.trim(), top_k: topK }),
      })
      toast.success("Settings saved")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed")
    } finally {
      setSaving(false)
    }
  }

  async function handleSavePolicy() {
    const sim = Number(minSimilarity)
    const strong = Number(minStrong)
    if (!Number.isFinite(sim) || sim < 0 || sim > 1) {
      toast.error("Grounding threshold must be between 0 and 1")
      return
    }
    if (!Number.isInteger(strong) || strong < 0 || strong > 20) {
      toast.error("Sources required must be a whole number from 0 to 20")
      return
    }
    setSavingPolicy(true)
    try {
      await api(`/api/projects/${project.id}`, {
        method: "PATCH",
        // Blank strings, not nulls: null means "leave it alone", so it cannot
        // double as the clear signal - same contract as description.
        body: JSON.stringify({
          min_similarity: sim,
          min_strong: strong,
          answer_language: answerLanguage.trim(),
          answer_disclaimer: answerDisclaimer.trim(),
          document_language: documentLanguage.trim(),
          answer_language_strict: languageStrict,
          version_tracking: versionTracking,
        }),
      })
      toast.success("Answer policy saved")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed")
    } finally {
      setSavingPolicy(false)
    }
  }

  async function handleSaveLlm() {
    const [provider, model] = llm.split("/", 2)
    const body: Record<string, unknown> = {
      llm_provider: provider,
      llm_model: model,
    }
    if (llmKeyInput.trim()) {
      body.llm_api_key = llmKeyInput.trim()
    } else if (provider !== project.llm_provider && project.llm_key_last4) {
      // Switching providers without a new key: the stored override belonged to
      // the old provider, so drop it and fall back to the account key.
      body.llm_api_key = ""
    }
    // A pasted key gets the encrypting animation (with a minimum display so
    // it reads, not flashes); a plain model change stays quiet.
    const encrypting = Boolean(body.llm_api_key)
    setSavingLlm(true)
    if (encrypting) setEncryptingLlm(true)
    try {
      await Promise.all([
        api(`/api/projects/${project.id}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        }),
        encrypting
          ? new Promise((resolve) => setTimeout(resolve, 1400))
          : Promise.resolve(),
      ])
      toast.success("Answer model saved")
      setLlmKeyInput("")
      setLlmEditingKey(false)
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed")
    } finally {
      setSavingLlm(false)
      setEncryptingLlm(false)
    }
  }

  async function patchLlmKey(value: string) {
    const encrypting = value !== ""
    setSavingLlm(true)
    if (encrypting) setEncryptingLlm(true)
    try {
      await Promise.all([
        api(`/api/projects/${project.id}`, {
          method: "PATCH",
          body: JSON.stringify({ llm_api_key: value }),
        }),
        encrypting
          ? new Promise((resolve) => setTimeout(resolve, 1400))
          : Promise.resolve(),
      ])
      toast.success(value === "" ? "Reverted to account key" : "Project key saved")
      setLlmKeyInput("")
      setLlmEditingKey(false)
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update key")
    } finally {
      setSavingLlm(false)
      setEncryptingLlm(false)
    }
  }

  async function patchEmbeddingKey(value: string) {
    const encrypting = value !== ""
    setSavingEmbKey(true)
    if (encrypting) setEncryptingEmb(true)
    try {
      await Promise.all([
        api(`/api/projects/${project.id}`, {
          method: "PATCH",
          body: JSON.stringify({ embedding_api_key: value }),
        }),
        encrypting
          ? new Promise((resolve) => setTimeout(resolve, 1400))
          : Promise.resolve(),
      ])
      toast.success(value === "" ? "Reverted to account key" : "Project key saved")
      setEmbKeyInput("")
      setEmbEditingKey(false)
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update key")
    } finally {
      setSavingEmbKey(false)
      setEncryptingEmb(false)
    }
  }

  async function handleReindex() {
    const [embeddingProvider, embeddingModel] = embedding.split("/", 2)
    const body: Record<string, unknown> = {
      chunk_size: chunkSize,
      chunk_overlap: chunkOverlap,
      embedding_provider: embeddingProvider,
      embedding_model: embeddingModel,
      embedding_dimensions: embDimensions,
    }
    if (embKeyInput.trim()) {
      body.embedding_api_key = embKeyInput.trim()
    } else if (
      embeddingProvider !== project.embedding_provider &&
      project.embedding_key_last4
    ) {
      // Switching embedding providers without a new key: drop the stale
      // override so resolution falls back to the account key.
      body.embedding_api_key = ""
    }
    setReindexing(true)
    try {
      const requeued = await api<unknown[]>(
        `/api/projects/${project.id}/reindex`,
        { method: "POST", body: JSON.stringify(body) }
      )
      // Push the server's own updated file list straight into the Files tab's
      // cache. Two reasons this is not just an optimisation:
      //
      // 1. The Files tab polls only while its CACHED list already contains a
      //    pending/processing row (its refreshInterval is a function of the
      //    data). Re-indexing from over here left that cache showing
      //    "indexed", so the interval stayed 0, nothing ever refetched, and
      //    the tab sat frozen until a full page reload - the reported bug.
      // 2. Seeding rather than revalidating means the rows flip to "queued"
      //    on the same tick, with no request and no empty frame.
      //
      // Deliberately NOT added to onChanged(): files-tab's useSWR has
      // onSuccess -> onChanged, so invalidating this key from there would make
      // every refetch trigger another one, for ever.
      globalMutate(`/api/projects/${project.id}/files`, requeued, {
        revalidate: false,
      })
      toast.success(
        !hasFiles
          ? "Embedding configuration saved"
          : instantShrink
            ? "Vector size reduced - originals kept, nothing re-embedded"
            : instantRestore
              ? "Vector size restored from the kept originals - nothing re-embedded"
              : "Re-indexing started - files are being re-embedded"
      )
      setConfirmReindex(false)
      setEmbKeyInput("")
      setEmbEditingKey(false)
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Re-index failed")
    } finally {
      setReindexing(false)
    }
  }

  async function handleSuspend() {
    const resume = project.suspended
    setSuspending(true)
    try {
      await api(`/api/projects/${project.id}/${resume ? "resume" : "suspend"}`, {
        method: "POST",
      })
      toast.success(resume ? "Project resumed" : "Project suspended")
      setConfirmSuspend(false)
      onChanged()
      globalMutate("/api/projects")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Action failed")
    } finally {
      setSuspending(false)
    }
  }

  async function handleDelete() {
    deleteDone.current = false
    setDeleting(true)
    try {
      await api(`/api/projects/${project.id}`, { method: "DELETE" })
      // Drop it from the dashboard/sidebar list right away so the deleted card
      // is gone the instant we navigate back (no stale flash before revalidate).
      globalMutate<Project[]>(
        "/api/projects",
        (list) => list?.filter((p) => p.id !== project.id),
        { revalidate: false }
      )
      // Don't navigate yet - let the loader finish its current animation cycle.
      deleteDone.current = true
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed")
      setDeleting(false)
    }
  }

  function handleDeleteCycle() {
    if (!deleteDone.current) return
    deleteDone.current = false
    toast.success("Project deleted")
    router.push("/dashboard")
  }

  const overview: { label: string; value: string }[] = [
    {
      label: "Answer model",
      value: `${project.llm_provider} / ${project.llm_model}`,
    },
    {
      label: "Embedding",
      value: `${project.embedding_provider} / ${project.embedding_model}`,
    },
    { label: "Dimensions", value: `${project.embedding_dimensions}d` },
    {
      label: "Chunking",
      value: `${project.chunk_size} / ${project.chunk_overlap}`,
    },
    { label: "Top-K", value: String(project.top_k) },
    { label: "Files", value: String(project.file_count) },
    { label: "Chunks", value: String(project.chunk_count) },
    { label: "Status", value: project.status },
  ]

  return (
    <div className="space-y-4">
      {/* At-a-glance summary of the project's live configuration. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Gauge className="size-4 text-muted-foreground" />
            Overview
          </CardTitle>
          <CardDescription>
            This project&apos;s current configuration at a glance.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
          {overview.map((item) => (
            <div
              key={item.label}
              className="rounded-lg border bg-muted/30 px-3 py-2.5"
            >
              <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                {item.label}
              </div>
              <div
                className="mt-0.5 truncate text-sm font-medium capitalize"
                title={item.value}
              >
                {item.value}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1 space-y-1.5">
              <CardTitle className="flex items-center gap-2">
                <Scales className="size-4 text-muted-foreground" />
                Answer policy
              </CardTitle>
              <CardDescription>
                Set the evidence bar for an answer, then control how every
                response is presented.
              </CardDescription>
            </div>
            <BestPractices
              className="ml-auto"
              tips={[
                {
                  visual: <GroundingViz />,
                  title: "Raise the floor before you raise the count",
                  detail:
                    "Minimum similarity decides what counts as evidence at all; required sources decides how much of it is enough. A project answering from weak matches usually needs a higher floor, not more sources - more sources at a low floor just adds more weak ones.",
                },
                {
                  title: "Required sources 0 means it always answers",
                  detail:
                    "It will answer from whatever it found, however thin. Set 1 or more when a wrong confident answer costs more than a clarifying question - policy, legal, medical and safety content usually qualify.",
                },
                {
                  visual: <TranslateViz />,
                  title: "Leave the language matching unless the audience is fixed",
                  detail:
                    "By default each answer comes back in the language its question was asked in, even when every document is in another language - a Tamil question against an English handbook is answered in Tamil. Pin a language only when every reader wants the same one, like a public help centre.",
                },
                {
                  title: "Keep languages in separate projects",
                  detail:
                    "A question in a script your documents do not use is translated before searching, which is what makes cross-language questions work. That is skipped when the project already contains that script - so English and Hindi files in ONE project means a Hindi question reaches only the Hindi half.",
                },
                {
                  title: "Set the document language if your files are not English",
                  detail:
                    "Keyword search stems words, and until you set this it stems them as English. A Russian search for the singular will not find the plural; with the language set, it will. Measured to rescue searches in Russian, German, Spanish, Portuguese, Italian, Dutch, Hindi, Nepali, Arabic and Indonesian among others. It re-stems the index in place — nothing is re-embedded and no provider key is touched.",
                },
                {
                  title: "The standing notice is copied, not summarised",
                  detail:
                    "It is appended to every answer word for word, so a regulator-facing notice cannot be softened by the model. It also lands on cached answers, and changing it invalidates them.",
                },
                {
                  title: "Version tracking is for editions, not filenames",
                  detail:
                    "Nothing is deleted. Turn it on where a later document replaces an earlier one that is still here - a contract and its amended-and-restated version, a policy reissued with a new effective date, a standard's next edition, a statute and its consolidated reprint, an article and its erratum. Elsewhere, files are held for a confirmation that changes nothing.",
                },
              ]}
            />
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid min-w-0 gap-6 lg:grid-cols-2 lg:gap-0">
            <section className="min-w-0 space-y-4 lg:pr-6">
              <div className="space-y-1">
                <h3 className="text-sm font-medium">Grounding</h3>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Decide how much matching evidence the project needs before it
                  answers.
                </p>
              </div>
              <div className="grid min-w-0 gap-4 sm:grid-cols-2">
                <div className="min-w-0 space-y-2">
                  <Label htmlFor="settings-minsim">Minimum similarity</Label>
                  <Input
                    id="settings-minsim"
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={minSimilarity}
                    onChange={(e) => setMinSimilarity(e.target.value)}
                  />
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    Match score from 0 to 1. Lower-scoring chunks are ignored;
                    0.2 is the permissive default.
                  </p>
                </div>
                <div className="min-w-0 space-y-2">
                  <Label htmlFor="settings-minstrong">Required sources</Label>
                  <Input
                    id="settings-minstrong"
                    type="number"
                    min={0}
                    max={20}
                    step={1}
                    value={minStrong}
                    onChange={(e) => setMinStrong(e.target.value)}
                  />
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    Ask for clarification when fewer sources qualify. Set 0 to
                    always answer.
                  </p>
                </div>
              </div>
            </section>

            <section className="min-w-0 space-y-4 border-t pt-6 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-6">
              <div className="space-y-1">
                <h3 className="text-sm font-medium">Language &amp; format</h3>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  What your documents are written in, and how every response is
                  presented.
                </p>
              </div>
              <div className="grid min-w-0 gap-4 sm:grid-cols-2">
                <div className="min-w-0 space-y-2">
                  <Label htmlFor="settings-lang">Answer language</Label>
                  <Select
                    value={answerLanguage || MATCH_QUESTION}
                    onValueChange={(v) =>
                      setAnswerLanguage(v === MATCH_QUESTION ? "" : v)
                    }
                  >
                    <SelectTrigger id="settings-lang" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={MATCH_QUESTION}>
                        Match the question
                      </SelectItem>
                      {/* A value set before this was a menu - or through the
                          API, which still accepts any string - would otherwise
                          vanish from the trigger and be silently overwritten on
                          the next save. */}
                      {answerLanguage &&
                        !ANSWER_LANGUAGES.includes(answerLanguage) && (
                          <SelectItem value={answerLanguage}>
                            {answerLanguage}
                          </SelectItem>
                        )}
                      {ANSWER_LANGUAGES.map((lang) => (
                        <SelectItem key={lang} value={lang}>
                          {lang}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {answerLanguage ? (
                    <div className="flex items-start gap-2.5 pt-0.5">
                      <Switch
                        id="settings-lang-strict"
                        checked={languageStrict}
                        onCheckedChange={setLanguageStrict}
                      />
                      <Label
                        htmlFor="settings-lang-strict"
                        className="cursor-pointer text-xs font-normal leading-relaxed text-muted-foreground"
                      >
                        Always use it
                      </Label>
                    </div>
                  ) : null}
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {!answerLanguage
                      ? "Each answer mirrors its own question, even when the documents are in another language."
                      : languageStrict
                        ? `Every answer is written in ${answerLanguage}, whatever language the question was asked in.`
                        : `${answerLanguage} unless the question is asked in another language — then the answer follows the question.`}
                  </p>
                </div>
                <div className="min-w-0 space-y-2">
                  <Label htmlFor="settings-doclang">Document language</Label>
                  <Select
                    value={documentLanguage || "English"}
                    onValueChange={(v) =>
                      setDocumentLanguage(v === "English" ? "" : v)
                    }
                  >
                    <SelectTrigger id="settings-doclang" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {/* A value the API accepted but this build has no
                          stemmer for would otherwise vanish from the trigger
                          and be silently overwritten on the next save. */}
                      {documentLanguage &&
                        !DOCUMENT_LANGUAGES.includes(documentLanguage) && (
                          <SelectItem value={documentLanguage}>
                            {documentLanguage}
                          </SelectItem>
                        )}
                      {DOCUMENT_LANGUAGES.map((lang) => (
                        <SelectItem key={lang} value={lang}>
                          {lang}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    What your files are written in. Keyword search stems words
                    in this language, so a search finds other forms of the same
                    word. Changing it re-stems the index in place — nothing is
                    re-embedded.
                  </p>
                </div>
                <div className="min-w-0 space-y-2">
                  <Label htmlFor="settings-disclaimer">Standing notice</Label>
                  <Textarea
                    id="settings-disclaimer"
                    rows={2}
                    placeholder="No notice"
                    value={answerDisclaimer}
                    onChange={(e) => setAnswerDisclaimer(e.target.value)}
                  />
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    Appended verbatim to every answer when provided.
                  </p>
                </div>
              </div>
            </section>
          </div>

          <div className="mt-6 flex flex-col gap-4 border-t pt-5 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 space-y-1.5">
              <div className="flex items-center gap-2.5">
                <Switch
                  id="version-tracking"
                  checked={versionTracking}
                  disabled={!project.version_extraction_available}
                  onCheckedChange={setVersionTracking}
                />
                <Label
                  htmlFor="version-tracking"
                  className="cursor-pointer text-sm font-medium"
                >
                  Track document versions
                </Label>
              </div>
              <p className="max-w-3xl text-xs leading-relaxed text-muted-foreground">
                Hold likely new editions for confirmation. It fits documents
                that come in editions, not ordinary working files, where a draft
                named report_v2 is held out of answers until someone confirms
                it. Replaced versions remain downloadable but stop contributing
                to answers. Switching it on also reads the titles of documents
                already here, so they can be recognised as earlier editions.
              </p>
              {!project.version_extraction_available && (
                <p className="max-w-3xl text-xs leading-relaxed text-amber-700 dark:text-amber-400">
                  Turned off for this deployment. Ask an administrator to
                  enable document version extraction.
                </p>
              )}
            </div>
            <Button
              className="shrink-0 sm:min-w-28"
              onClick={handleSavePolicy}
              disabled={savingPolicy}
            >
              {savingPolicy ? <Spin /> : "Save policy"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Two cards per row from lg+; stretch so each row's cards share a height.
          grid-cols-1 is load-bearing on mobile: without a template the implicit
          auto track sizes to the widest card's min-content (long model labels),
          overflowing the viewport - minmax(0,1fr) clamps it. */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1 space-y-1.5">
              <CardTitle className="flex items-center gap-2">
                <GearSix className="size-4 text-muted-foreground" />
                General
              </CardTitle>
              <CardDescription>These take effect immediately.</CardDescription>
            </div>
            <BestPractices
              className="ml-auto"
              tips={[
                {
                  visual: <CostViz />,
                  title: "Model switches re-embed everything",
                  detail:
                    "Chunks are wiped and re-ingested, and memory embeddings are re-embedded with the new model. Budget embedding cost before switching on a large project.",
                },
                {
                  visual: <DimensionsViz />,
                  title: "Shrinking dimensions is free",
                  detail:
                    "Same Matryoshka model at a smaller size (e.g. 3072 to 1024) truncates stored vectors in place - instant, no API calls. Growing back requires a full re-index.",
                },
                {
                  visual: <KeyViz />,
                  title: "Key changes are instant",
                  detail:
                    "Replacing a provider key never re-indexes anything - only model and chunking changes do.",
                },
                {
                  visual: <OverrideViz />,
                  title: "Project keys override account keys",
                  detail:
                    "A key set here wins over the account-level key for this project only - handy for separate billing or rate limits.",
                },
                {
                  visual: <TopKViz />,
                  title: "top_k trades recall for noise",
                  detail:
                    "More retrieved chunks catch more facts but dilute the context. 5 suits focused questions; raise it for broad, multi-part ones.",
                },
              ]}
            />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="settings-name">Project name</Label>
            <Input
              id="settings-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={20}
            />
            <div
              className={`text-right text-xs tabular-nums ${
                name.length >= 20
                  ? "text-amber-600 dark:text-amber-400"
                  : "text-muted-foreground"
              }`}
            >
              {name.length}/20
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="settings-description">Description (optional)</Label>
            <Textarea
              id="settings-description"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Shown on the project card and searched from the sidebar.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="settings-topk">Top-K results</Label>
            <Input
              id="settings-topk"
              type="number"
              min={1}
              max={20}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
            />
          </div>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? <Spin /> : "Save"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ChatCircle className="size-4 text-muted-foreground" />
            Answer model (LLM)
          </CardTitle>
          <CardDescription>
            The chat model used to write answers. Only providers you have a key
            for appear - add more in{" "}
            <a href="/settings/api-keys" className="underline">
              Settings → API keys
            </a>
            .
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Model</Label>
            <Select value={llm} onValueChange={changeLlm}>
              <SelectTrigger className={cn("w-full", !llmCurrentUsable && "text-muted-foreground")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {models ? (
                  Object.entries(models.catalog.llm).flatMap(([provider, names]) =>
                    names
                      .filter((model) => {
                        if (`${provider}/${model}` === llm) return true
                        // Retired by the vendor. Kept resolvable so existing
                        // projects keep answering, but never offered again -
                        // some of these now silently redirect to a different,
                        // differently-priced model.
                        if (isDeprecated(models, "llm", provider, model))
                          return false
                        return providerUsable(provider, "llm", availability, project)
                      })
                      .map((model) => {
                        const usable = providerUsable(
                          provider,
                          "llm",
                          availability,
                          project
                        )
                        const retired = isDeprecated(models, "llm", provider, model)
                        return (
                          <SelectItem
                            key={`${provider}/${model}`}
                            value={`${provider}/${model}`}
                            className={cn(
                              (!usable || retired) &&
                                "text-muted-foreground opacity-70"
                            )}
                          >
                            {provider} / {model}
                            {retired
                              ? " · retired - switch model"
                              : !usable
                                ? " · key removed"
                                : ""}
                          </SelectItem>
                        )
                      })
                  )
                ) : (
                  <SelectItem value={llm}>{llm}</SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>
          {encryptingLlm ? (
            <EncryptingLoader rows={3} />
          ) : (
            <ProviderKeyField
              provider={llmProvider}
              last4={llmOverrideLast4}
              accountHasKey={llmAccountHasKey}
              value={llmKeyInput}
              onChange={setLlmKeyInput}
              editing={llmEditingKey}
              onEditingChange={setLlmEditingKey}
              onRemove={() => patchLlmKey("")}
              busy={savingLlm}
            />
          )}
          {!encryptingLlm && (llmEditingKey || llmForcedInput || llmChanged) && (
            <div className="flex gap-2">
              {llmEditingKey && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setLlmKeyInput("")
                    setLlmEditingKey(false)
                  }}
                >
                  Cancel
                </Button>
              )}
              <Button onClick={handleSaveLlm} disabled={!canSaveLlm || savingLlm}>
                {savingLlm ? <Spin /> : "Save"}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cube className="size-4 text-muted-foreground" />
            Indexing &amp; embedding
          </CardTitle>
          <CardDescription>
            The embedding model turns text into vectors. Changing the model or
            chunking re-processes every file; changing only the key is instant.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="settings-chunk-size">Chunk size</Label>
              <Input
                id="settings-chunk-size"
                type="number"
                min={100}
                max={8000}
                value={chunkSize}
                onChange={(e) => setChunkSize(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="settings-chunk-overlap">Chunk overlap</Label>
              <Input
                id="settings-chunk-overlap"
                type="number"
                min={0}
                value={chunkOverlap}
                onChange={(e) => setChunkOverlap(Number(e.target.value))}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label>Embedding model</Label>
            <Select value={embedding} onValueChange={changeEmbedding}>
              <SelectTrigger className={cn("w-full", !embCurrentUsable && "text-muted-foreground")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {models ? (
                  Object.entries(models.catalog.embedding).flatMap(
                    ([provider, entries]) =>
                      entries
                        .filter((entry) => {
                          // The current selection is never hidden - a project
                          // sitting on a retired model has to be able to SEE
                          // what it is in order to move off it.
                          if (`${provider}/${entry.model}` === embedding)
                            return true
                          // Retired upstream: still resolvable server-side for
                          // projects that already chose it, but offering it to
                          // anyone else builds a project that cannot index.
                          if (
                            isDeprecated(models, "embedding", provider, entry.model)
                          )
                            return false
                          return providerUsable(
                            provider,
                            "embedding",
                            availability,
                            project
                          )
                        })
                        .map((entry) => {
                          const usable = providerUsable(
                            provider,
                            "embedding",
                            availability,
                            project
                          )
                          return (
                            <SelectItem
                              key={`${provider}/${entry.model}`}
                              value={`${provider}/${entry.model}`}
                              className={cn(
                                (!usable ||
                                  isDeprecated(
                                    models,
                                    "embedding",
                                    provider,
                                    entry.model
                                  )) &&
                                  "text-muted-foreground opacity-70"
                              )}
                            >
                              {provider} / {entry.model} ({entry.dimensions}d)
                              {isDeprecated(
                                models,
                                "embedding",
                                provider,
                                entry.model
                              )
                                ? " · retired - switch model"
                                : !usable
                                  ? " · key removed"
                                  : ""}
                            </SelectItem>
                          )
                        })
                  )
                ) : (
                  <SelectItem value={embedding}>{embedding}</SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>
          {embDimOptions.length > 1 && (
            <div className="space-y-2">
              <Label>Vector dimensions</Label>
              <Select
                value={String(embDimensions)}
                onValueChange={(v) => setEmbDimensions(Number(v))}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {embDimOptions.map((d) => (
                    <SelectItem key={d} value={String(d)}>
                      {d}d{d === embEntry?.dimensions ? " (default)" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {instantChange && (
                <p className="rounded-md bg-sky-50 px-3 py-2 text-xs text-sky-800 dark:bg-sky-950/40 dark:text-sky-300">
                  {instantShrink
                    ? "Same model, smaller size: applied instantly, and your full-size vectors are kept so you can switch back."
                    : "Restoring a size you used before: applied instantly from the kept copies - no re-embedding."}
                </p>
              )}
            </div>
          )}
          {encryptingEmb ? (
            <EncryptingLoader rows={3} />
          ) : (
            <ProviderKeyField
              provider={embProvider}
              last4={embOverrideLast4}
              accountHasKey={embAccountHasKey}
              value={embKeyInput}
              onChange={setEmbKeyInput}
              editing={embEditingKey}
              onEditingChange={setEmbEditingKey}
              onRemove={() => patchEmbeddingKey("")}
              busy={savingEmbKey}
            />
          )}
          {!encryptingEmb && (reindexNeeded || embEditingKey || embForcedInput) && (
            <div className="flex gap-2">
              {embEditingKey && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setEmbKeyInput("")
                    setEmbEditingKey(false)
                  }}
                >
                  Cancel
                </Button>
              )}
              {reindexNeeded ? (
                <Button
                  // With no files there's nothing to re-index, so skip the
                  // confirmation and just persist the config change.
                  onClick={() =>
                    hasFiles ? setConfirmReindex(true) : handleReindex()
                  }
                  disabled={!embUsable || reindexing}
                >
                  {reindexing ? (
                    <Spin />
                  ) : !hasFiles ? (
                    "Save changes"
                  ) : instantChange ? (
                    // No re-index happens on this path - promising one would
                    // make a free, instant action look expensive.
                    "Change dimensions"
                  ) : (
                    "Change & re-index"
                  )}
                </Button>
              ) : (
                <Button
                  onClick={() => patchEmbeddingKey(embKeyInput.trim())}
                  disabled={!embKeyOnly || savingEmbKey}
                >
                  {savingEmbKey ? <Spin /> : "Save"}
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-destructive/40 bg-destructive/[0.02]">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-destructive">
            <WarningOctagon className="size-4" />
            Danger zone
          </CardTitle>
          <CardDescription>
            Suspend to pause access, or delete to remove the project entirely.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Suspend / resume - reversible, above the destructive delete. */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-medium">
                {project.suspended ? "Resume project" : "Suspend project"}
              </p>
              <p className="text-xs text-muted-foreground">
                {project.suspended
                  ? "This project is suspended - its keys and API are blocked. Resume to reactivate."
                  : "Pause all API keys and external access (public API + MCP). Your data is kept; reversible any time."}
              </p>
            </div>
            <Button
              variant="outline"
              className="shrink-0 border-amber-500/50 bg-amber-400/10 text-amber-700 hover:bg-amber-400/20 hover:text-amber-800 dark:text-amber-400 dark:hover:text-amber-300"
              onClick={() => setConfirmSuspend(true)}
            >
              {project.suspended ? "Resume" : "Suspend"}
            </Button>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-destructive/20 pt-4">
            <div className="min-w-0">
              <p className="text-sm font-medium text-destructive">Delete project</p>
              <p className="text-xs text-muted-foreground">
                Permanently remove{" "}
                <span className="font-medium text-foreground">{project.name}</span>{" "}
                and everything in it. Cannot be undone.
              </p>
            </div>
            <Button
              variant="destructive"
              className="shrink-0"
              onClick={() => setConfirmDelete(true)}
            >
              Delete project
            </Button>
          </div>
        </CardContent>
      </Card>
      </div>

      <Dialog open={confirmReindex} onOpenChange={setConfirmReindex}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {instantShrink
                ? "Shrink vector dimensions?"
                : instantRestore
                  ? "Restore vector dimensions?"
                  : "Re-index all files?"}
            </DialogTitle>
            {/* Three genuinely different operations, and the difference the
                user cares about is whether it COSTS anything. The old copy
                warned that "growing back later requires a full re-index" - true
                when a shrink threw the wide numbers away, and now the opposite
                of what happens. Wording that scares someone off a free action
                is as costly as wording that hides a paid one. */}
            <DialogDescription>
              {instantShrink
                ? `Vectors are cut to ${embDimensions} dimensions instantly - ` +
                  "nothing is re-embedded and no API calls are made. Your " +
                  `full-size ${project.embedding_dimensions}-dimension vectors ` +
                  "are kept, so you can switch back later just as quickly."
                : instantRestore
                  ? `Your ${embDimensions}-dimension vectors are restored from ` +
                    "the copies kept when you shrank - instantly, with no " +
                    "re-embedding and no API calls. Files added while shrunk " +
                    "are re-embedded on their own if they need it."
                  : `All ${project.file_count} file(s) will be re-embedded with ` +
                    "the new configuration, which uses your provider key. Text " +
                    "already extracted is reused, so documents are not " +
                    "re-converted. Queries may return incomplete results until " +
                    "indexing finishes."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmReindex(false)}>
              Cancel
            </Button>
            <Button onClick={handleReindex} disabled={reindexing}>
              {reindexing ? (
                <Spin />
              ) : instantShrink ? (
                "Shrink"
              ) : instantRestore ? (
                "Restore"
              ) : (
                "Re-index"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={confirmSuspend}
        onOpenChange={(open) => {
          if (!open && !suspending) setConfirmSuspend(false)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {project.suspended ? "Resume this project?" : "Suspend this project?"}
            </DialogTitle>
            <DialogDescription>
              {project.suspended
                ? "The project's API keys and endpoints will start working again immediately."
                : "All of this project's API keys stop working and the public API + MCP return 403 until you resume. Files, chunks, memories and keys are kept - nothing is deleted."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmSuspend(false)}
              disabled={suspending}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSuspend}
              disabled={suspending}
              className={
                project.suspended
                  ? undefined
                  : "bg-amber-500 text-white hover:bg-amber-500/90"
              }
            >
              {suspending ? (
                <Spin />
              ) : project.suspended ? (
                "Resume project"
              ) : (
                "Suspend project"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={confirmDelete}
        onOpenChange={(open) => {
          if (!open && !deleting) setConfirmDelete(false)
        }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete {project.name}?</DialogTitle>
            {!deleting && (
              <DialogDescription>
                This permanently removes the project, its files, index, and API
                keys. Apps calling its endpoint will break.
              </DialogDescription>
            )}
          </DialogHeader>
          {deleting ? (
            <div className="flex flex-col items-center gap-3 py-4">
              <BoxLoader scale={0.5} onCycle={handleDeleteCycle} />
              <p className="text-xs text-muted-foreground">
                Permanently deleting…
              </p>
            </div>
          ) : (
            <DialogFooter>
              <Button variant="outline" onClick={() => setConfirmDelete(false)}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={handleDelete}>
                Delete forever
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
