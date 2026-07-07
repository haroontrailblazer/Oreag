"use client"

import { Brain, MagnifyingGlass as Search } from "@phosphor-icons/react/dist/ssr"
import { useState } from "react"
import { toast } from "@/lib/toast"
import useSWR from "swr"

import { Badge } from "@/components/ui/badge"
import { BestPractices } from "@/components/ui/best-practices"
import {
  MemoryViz,
  RetrievalViz,
} from "@/components/ui/best-practice-visuals"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { api, fetcher } from "@/lib/api"
import type { Memory, Project } from "@/lib/types"

const BEST_PRACTICE_TIPS = [
  {
    visual: <MemoryViz />,
    title: "One fact per memory",
    detail:
      "Short, self-contained memories retrieve better than long notes - they embed into a single clean vector, like a good chunk.",
  },
  {
    visual: <MemoryViz />,
    title: "Tag for humans, not for search",
    detail:
      "Search is semantic (meaning-based). Tags help YOU filter and audit this list - they do not boost retrieval.",
  },
  {
    visual: <MemoryViz />,
    title: "Pin what must persist",
    detail:
      "Pinned memories are protected from bulk cleanup - use pins for decisions and constraints agents must never lose.",
  },
  {
    visual: <RetrievalViz />,
    title: "Memories join RAG answers",
    detail:
      "Relevant memories are blended into /query answers alongside document chunks (shown as memory sources), and they live in the same vector space as your files.",
  },
  {
    visual: <MemoryViz />,
    title: "Unembedded memories are invisible",
    detail:
      "A memory saved while no embedding key was available has no vector and cannot be searched - re-save it (or change models) to embed it.",
  },
]

export function MemoryTab({ project }: { project: Project }) {
  const { data: memories, error, mutate } = useSWR<Memory[]>(
    `/api/projects/${project.id}/memory`,
    fetcher
  )
  const [filter, setFilter] = useState("")

  const loading = memories === undefined && !error
  const all = memories ?? []
  const term = filter.trim().toLowerCase()
  const shown = all.filter((m) => m.content.toLowerCase().includes(term))

  async function handleDelete(id: number) {
    try {
      await api(`/api/projects/${project.id}/memory/${id}`, { method: "DELETE" })
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete")
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Agent memory</CardTitle>
            <CardDescription>
              Notes your connected agents (via the MCP server) have saved for
              this project.
            </CardDescription>
          </div>
          <BestPractices tips={BEST_PRACTICE_TIPS} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            placeholder="Filter memories"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            disabled={all.length === 0 && !loading}
            className="pl-8"
          />
        </div>
        {error ? (
          <p className="text-sm text-destructive">
            Could not load memories: {error.message}
          </p>
        ) : loading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-16 rounded-md" />
            ))}
          </div>
        ) : all.length === 0 ? (
          <div className="py-10 text-center">
            <div className="mx-auto mb-3 flex size-11 items-center justify-center rounded-xl bg-muted text-muted-foreground">
              <Brain className="size-5" />
            </div>
            <p className="text-sm font-medium">No memories yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Notes your connected agents save will appear here.
            </p>
          </div>
        ) : shown.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No memories match &ldquo;{filter.trim()}&rdquo;.
          </p>
        ) : (
          shown.map((m) => (
            <div
              key={m.id}
              className="flex items-start justify-between gap-3 rounded-md border p-3"
            >
              <div className="min-w-0 space-y-1">
                <p className="text-sm">{m.content}</p>
                <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                  {m.pinned && <Badge variant="secondary">pinned</Badge>}
                  {m.tags.map((t) => (
                    <Badge key={t} variant="outline">
                      {t}
                    </Badge>
                  ))}
                  <span>{m.source}</span>
                  <span>· {new Date(m.created_at).toLocaleDateString()}</span>
                </div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => handleDelete(m.id)}>
                Delete
              </Button>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  )
}
