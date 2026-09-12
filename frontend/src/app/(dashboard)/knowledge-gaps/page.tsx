import { KnowledgeGapsDashboard } from "@/components/knowledge-gaps"

export default async function KnowledgeGapsPage({ searchParams }: { searchParams: Promise<{ project?: string }> }) {
  const { project } = await searchParams
  const initialProject = project && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(project) ? project : ""
  return <KnowledgeGapsDashboard key={initialProject} initialProject={initialProject} />
}
