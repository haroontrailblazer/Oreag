import type {
  DeprecatedModels,
  EmbeddingModelEntry,
  ModelsResponse,
  Project,
} from "@/lib/types"

/**
 * Is this model retired by its provider?
 *
 * One helper for both roles because there are two declaration sites - an inline
 * flag on embedding entries, a lookup for LLMs - and a picker that consulted
 * only one of them would keep offering half the dead models. Callers must still
 * exempt the CURRENT selection: a project already on a retired model has to be
 * able to see what it is in order to move off it.
 */
export function isDeprecated(
  models: ModelsResponse | undefined,
  role: ModelRole,
  provider: string,
  model: string
): boolean {
  const listed = (models?.deprecated as DeprecatedModels | undefined)?.[role]?.[
    provider
  ]
  if (listed?.includes(model)) return true
  if (role !== "embedding") return false
  return Boolean(
    models?.catalog.embedding[provider]?.find((e) => e.model === model)
      ?.deprecated
  )
}

export type Availability = Record<string, boolean>
export type ModelRole = "llm" | "embedding"

/** Vector sizes a model can produce (MRL prefixes, or just its native size). */
export function dimensionOptions(entry: EmbeddingModelEntry): number[] {
  return entry.dimension_options ?? [entry.dimensions]
}

/** Providers that run locally and never need an API key. */
export const KEYLESS_PROVIDERS = new Set([
  "ollama",
  "lmstudio",
  "sentence_transformers",
])

/** The provider half of a `"provider/model"` value. */
export function providerOf(value: string): string {
  return value.split("/", 1)[0]
}

/** The masked last4 of this project's override key for a role (null if none). */
export function overrideLast4(
  project: Pick<Project, "llm_key_last4" | "embedding_key_last4">,
  role: ModelRole
): string | null {
  return role === "llm" ? project.llm_key_last4 : project.embedding_key_last4
}

/** The provider this project currently uses for a role. */
export function projectProvider(
  project: Pick<Project, "llm_provider" | "embedding_provider">,
  role: ModelRole
): string {
  return role === "llm" ? project.llm_provider : project.embedding_provider
}

/**
 * Account-level check (no project context): does this provider need a key the
 * account doesn't have? Used by the new-project wizard. Keyless local providers
 * never "need a key" - their availability reflects whether they're reachable.
 */
export function needsKey(provider: string, availability: Availability): boolean {
  return !KEYLESS_PROVIDERS.has(provider) && !availability[provider]
}

/**
 * Can this provider's models be used for `role` in THIS project?
 *
 * True when the account has a key for the provider (account-level availability),
 * OR this project has an override key that currently points at this provider.
 * The second clause is what makes a per-project key unlock that provider's
 * models in the playground / model pickers.
 */
export function providerUsable(
  provider: string,
  role: ModelRole,
  availability: Availability,
  project: Pick<
    Project,
    | "llm_provider"
    | "embedding_provider"
    | "llm_key_last4"
    | "embedding_key_last4"
  >
): boolean {
  if (availability[provider]) return true
  return (
    projectProvider(project, role) === provider &&
    Boolean(overrideLast4(project, role))
  )
}

/**
 * Whether to flag a provider's models as "needs a key" in a project's picker:
 * it requires a key and this project has neither an account key nor a matching
 * override. Keyless local providers are never flagged.
 */
export function providerNeedsKey(
  provider: string,
  role: ModelRole,
  availability: Availability,
  project: Pick<
    Project,
    | "llm_provider"
    | "embedding_provider"
    | "llm_key_last4"
    | "embedding_key_last4"
  >
): boolean {
  return (
    !KEYLESS_PROVIDERS.has(provider) &&
    !providerUsable(provider, role, availability, project)
  )
}
