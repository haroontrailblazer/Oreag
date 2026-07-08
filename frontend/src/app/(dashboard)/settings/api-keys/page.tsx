import { ProjectKeys } from "@/components/settings/project-keys"
import { ProviderKeys } from "@/components/settings/provider-keys"

export default function ApiKeysPage() {
  // Fixed frame like the project pages: title/description never move, only
  // the tables' rows scroll. Desktop height is derived from the layout via
  // md:h-full (no hardcoded offset); mobile subtracts the sticky top bar +
  // padding (~6.25rem).
  return (
    <div className="flex h-[calc(100dvh-6.25rem)] min-h-0 flex-col gap-6 overflow-hidden md:h-full">
      <div className="shrink-0">
        <h1 className="text-2xl font-semibold">API keys</h1>
        <p className="text-sm text-muted-foreground">
          Your own provider keys (OpenAI, Gemini, Anthropic), shared across all
          your projects.
        </p>
      </div>
      <ProviderKeys />
      <ProjectKeys />
    </div>
  )
}
