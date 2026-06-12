"use client"

import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/api"
import type { Project, QueryResponse } from "@/lib/types"

export function PlaygroundTab({ project }: { project: Project }) {
  const [question, setQuestion] = useState("")
  const [result, setResult] = useState<QueryResponse | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleAsk() {
    if (!question.trim()) return
    setLoading(true)
    setResult(null)
    try {
      const response = await api<QueryResponse>(
        `/api/projects/${project.id}/query`,
        { method: "POST", body: JSON.stringify({ question }) }
      )
      setResult(response)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Query failed")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Test your RAG</CardTitle>
          <CardDescription>
            Ask a question — the same pipeline your API consumers will use.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            rows={3}
            placeholder="e.g. What does chapter 2 say about retrieval?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleAsk()
            }}
          />
          <Button onClick={handleAsk} disabled={loading || !question.trim()}>
            {loading ? "Thinking…" : "Ask"}
          </Button>
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Answer</CardTitle>
            <CardDescription>
              {result.model} · {result.latency_ms} ms
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="whitespace-pre-wrap text-sm">{result.answer}</p>
            {result.sources.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-sm font-medium">Sources</h3>
                {result.sources.map((source, i) => (
                  <details
                    key={i}
                    className="rounded-lg border px-3 py-2 text-sm"
                  >
                    <summary className="cursor-pointer">
                      [{i + 1}] {source.filename}
                      {source.page_number != null &&
                        ` — page ${source.page_number}`}{" "}
                      <span className="text-muted-foreground">
                        ({(source.similarity * 100).toFixed(0)}% match)
                      </span>
                    </summary>
                    <p className="mt-2 whitespace-pre-wrap text-muted-foreground">
                      {source.content}
                    </p>
                  </details>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
