"use client"

import { PlaygroundTab } from "./playground-tab"
import { EvaluationPlayground } from "./evaluation-playground"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { Project } from "@/lib/types"

export function PlaygroundWorkspace({ project }: { project: Project }) {
  return <Tabs defaultValue="conversation" className="min-h-0 flex-1">
    <TabsList aria-label="Playground mode" className="shrink-0">
      <TabsTrigger value="conversation">Conversation</TabsTrigger>
      <TabsTrigger value="evaluate">Evaluate</TabsTrigger>
    </TabsList>
    <TabsContent value="conversation" forceMount className="flex min-h-0 flex-1 flex-col"><PlaygroundTab project={project} /></TabsContent>
    <TabsContent value="evaluate" forceMount className="min-h-0 flex-1 overflow-y-auto"><EvaluationPlayground key={project.id} project={project} /></TabsContent>
  </Tabs>
}
