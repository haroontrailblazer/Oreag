import { BUDGETS_KEY } from "@/lib/budgets"
import { DEFAULT_GAP_FILTERS, knowledgeGapsKey } from "@/lib/knowledge-gaps"
import { KNOWLEDGE_HEALTH_KEY } from "@/lib/knowledge-health"
import { queryExplorerKey } from "@/lib/query-explorer"
import { qualityTrendsKey } from "@/lib/quality-trends"
import { DEFAULT_FAILURE_FILTERS, failureKey } from "@/lib/request-failures"
import { DEFAULT_USAGE_WINDOW, PASSKEYS_KEY, PROVIDER_KEYS_KEY, RECOVERY_KEY, TOTP_KEY, usageKey } from "@/lib/settings-data"

/** Use the pages' own keys and defaults so warming fills exactly what they read. */
export function dashboardDataKeys(href: string, projectIds: readonly string[]) {
  const { pathname, searchParams } = new URL(href, "https://oreag.invalid")
  switch (pathname) {
    case "/dashboard": return ["/api/projects"]
    case "/query-explorer": return [searchParams.get("view") === "failures" ? failureKey(DEFAULT_FAILURE_FILTERS) : queryExplorerKey()]
    case "/knowledge-gaps": {
      const requested = searchParams.get("project") ?? ""
      const project = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(requested) ? requested : ""
      if (project && !projectIds.includes(project)) return []
      return [knowledgeGapsKey({ ...DEFAULT_GAP_FILTERS, project })]
    }
    case "/knowledge-health": return [KNOWLEDGE_HEALTH_KEY, qualityTrendsKey("30", "")]
    case "/settings/usage": return [usageKey(DEFAULT_USAGE_WINDOW), BUDGETS_KEY, "/api/account/operations"]
    case "/settings/api-keys": return [PROVIDER_KEYS_KEY]
    case "/settings/profile": return [PASSKEYS_KEY, TOTP_KEY, RECOVERY_KEY]
    case "/projects/new": return ["/api/models"]
    default: {
      if (!projectIds.some(id => pathname === `/projects/${encodeURIComponent(id)}`)) return []
      const base = `/api${pathname}`
      const keys = [base, `${base}/files`]
      const tab = searchParams.get("tab")
      if (tab === "memory") keys.push(`${base}/memory`)
      if (tab === "api") keys.push(`${base}/keys`)
      return keys
    }
  }
}
