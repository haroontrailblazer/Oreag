import { ProjectKeys } from "@/components/settings/project-keys"
import { ProviderKeys } from "@/components/settings/provider-keys"

export default function ApiKeysPage() {
  // Fixed frame like the project pages: title/description never move, only
  // the tables' rows scroll (mobile chrome ~6.25rem, desktop p-8 = 4rem).
  return (
    <div className="flex h-[calc(100dvh-6.25rem)] flex-col gap-6 md:h-[calc(100dvh-4rem)]">
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
