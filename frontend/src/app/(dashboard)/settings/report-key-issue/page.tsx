"use client"

import { PaperPlaneTilt, Warning } from "@phosphor-icons/react/dist/ssr"
import Link from "next/link"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { toast } from "@/lib/toast"

const DEVELOPER_EMAIL = "haroonint144@gmail.com"

const PROVIDERS = [
  "OpenAI",
  "Google Gemini",
  "Anthropic (Claude)",
  "Azure OpenAI",
  "Mistral",
  "Cohere",
  "Together AI",
  "Fireworks AI",
  "xAI (Grok)",
  "Groq",
  "DeepSeek",
  "OpenRouter",
  "Perplexity",
  "Voyage AI",
  "Jina AI",
  "Sarvam AI",
  "Ollama (local)",
  "LM Studio (local)",
  "Other",
]

// Anything that looks like a real credential must never leave the machine:
// common API-key shapes (OpenAI sk-, Google AIza / Vertex AQ., generic long
// tokens) are blocked before the report is composed.
const SECRET_PATTERN =
  /(sk-[A-Za-z0-9_-]{10,}|AIza[0-9A-Za-z_-]{10,}|AQ\.[A-Za-z0-9._-]{10,}|xai-[A-Za-z0-9_-]{10,}|gsk_[A-Za-z0-9_-]{10,}|Bearer\s+[A-Za-z0-9._-]{15,})/

export default function ReportKeyIssuePage() {
  const [provider, setProvider] = useState("")
  const [description, setDescription] = useState("")

  function handleSubmit() {
    if (!provider) {
      toast.error("Pick the provider the key belongs to")
      return
    }
    if (description.trim().length < 10) {
      toast.error("Describe the problem in a sentence or two")
      return
    }
    if (SECRET_PATTERN.test(description)) {
      toast.error(
        "Your report seems to contain an API key - remove it. We never need your key, only the provider and the error."
      )
      return
    }
    const subject = `Oreag key issue: ${provider}`
    const body = [
      `Provider: ${provider}`,
      "",
      "Problem:",
      description.trim(),
      "",
      "- Sent from the Oreag dashboard (Settings -> Report a key problem)",
    ].join("\n")
    window.location.href = `mailto:${DEVELOPER_EMAIL}?subject=${encodeURIComponent(
      subject
    )}&body=${encodeURIComponent(body)}`
    toast.success("Opening your email app - press Send there to deliver the report")
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Report a key problem</h1>
        <p className="text-sm text-muted-foreground">
          A provider key that fails, isn&apos;t accepted, or isn&apos;t supported
          yet? Tell the developer what happened.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>What went wrong?</CardTitle>
          <CardDescription>
            The report is sent by email to the developer ({DEVELOPER_EMAIL}).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-start gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
            <Warning className="mt-0.5 size-4 shrink-0" />
            <p>
              Never include your API key or any other secret in this report. We
              only need the provider name and the error you see - reports that
              look like they contain a key are blocked.
            </p>
          </div>

          <div className="space-y-2">
            <Label>Which provider is the key for?</Label>
            <Select value={provider} onValueChange={setProvider}>
              <SelectTrigger>
                <SelectValue placeholder="Select a provider" />
              </SelectTrigger>
              <SelectContent>
                {PROVIDERS.map((p) => (
                  <SelectItem key={p} value={p}>
                    {p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="issue-description">Describe the problem</Label>
            <Textarea
              id="issue-description"
              rows={6}
              placeholder="What were you doing, and what error text did you see? e.g. 'Uploading a PDF fails with 401 UNAUTHENTICATED on Gemini embeddings.'"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div className="flex items-center justify-between gap-4">
            <Link
              href="/settings/api-keys"
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              Back to API keys
            </Link>
            <Button onClick={handleSubmit}>
              <PaperPlaneTilt className="size-4" />
              Submit report
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
