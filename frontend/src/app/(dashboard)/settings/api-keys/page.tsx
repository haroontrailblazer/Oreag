import { ProjectKeys } from "@/components/settings/project-keys"
import { ProviderKeys } from "@/components/settings/provider-keys"

export default function ApiKeysPage() {
  return (
    <div className="space-y-6">
      <div>
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
