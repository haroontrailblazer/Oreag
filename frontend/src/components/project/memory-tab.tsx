"use client"

import { useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { api, fetcher } from "@/lib/api"
import type { Memory, Project } from "@/lib/types"

export function MemoryTab({ project }: { project: Project }) {
  const { data: memories, mutate } = useSWR<Memory[]>(
    `/api/projects/${project.id}/memory`,
    fetcher
  )
  const [filter, setFilter] = useState("")
  const shown = (memories ?? []).filter((m) =>
    m.content.toLowerCase().includes(filter.trim().toLowerCase())
  )

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
        <CardTitle>Agent memory</CardTitle>
        <CardDescription>
          Notes your connected agents (via the MCP server) have saved for this
          project.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Input
          placeholder="Filter memories"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        {shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">No memories yet.</p>
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
