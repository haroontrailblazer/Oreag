"use client"

import { useState } from "react"
import { PlaygroundTab } from "./playground-tab"
import { EvaluationPlayground } from "./evaluation-playground"
import type { Project } from "@/lib/types"

export function PlaygroundWorkspace({ project }: { project: Project }) {
  const [evaluate, setEvaluate] = useState(false)
  const [visited, setVisited] = useState(false)
  return <>
    <div className={evaluate ? "hidden" : "flex min-h-0 flex-1 flex-col"}><PlaygroundTab project={project} onEvaluate={() => { setVisited(true); setEvaluate(true) }} /></div>
    {visited && <div className={evaluate ? "min-h-0 flex-1 overflow-y-auto" : "hidden"}><EvaluationPlayground key={project.id} project={project} onBack={() => setEvaluate(false)} /></div>}
  </>
}
