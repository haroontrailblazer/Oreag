"use client"

import {
  ChartBarIcon as ChartBar,
  InfoIcon as Info,
} from "@phosphor-icons/react/dist/ssr"
import { useState } from "react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "recharts"
import useSWR from "swr"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { fetcher, isSessionExpired } from "@/lib/api"
import {
  DEFAULT_USAGE_WINDOW,
  USAGE_WINDOWS,
  usageKey,
  type UsageWindow,
} from "@/lib/settings-data"
import type {
  AccountUsage,
  UsageByApiKey,
  UsageByModel,
  UsageByProject,
  UsageCaveats,
  UsageDaily,
  UsageTotals,
} from "@/lib/types"
import { cn } from "@/lib/utils"

/* ------------------------------------------------------------------------- *
 * Formatting
 *
 * The one rule that shapes everything here: null is NOT zero. A null token or
 * cost figure means the provider reported nothing - the number is unknown, and
 * printing "0" would claim the opposite. Every formatter therefore has a
 * null-aware component wrapper that renders "not measured" instead.
 * ------------------------------------------------------------------------- */

const intFmt = new Intl.NumberFormat("en-US")
const compactFmt = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
})

/** $12.34 normally; four decimals for sub-cent amounts so they don't read $0.00. */
function formatCost(value: number): string {
  const abs = Math.abs(value)
  if (abs > 0 && abs < 0.01) return `$${value.toFixed(4)}`
  return `$${value.toFixed(2)}`
}

/** "Aug 3" from "2026-08-03", parsed as local (new Date("YYYY-MM-DD") is UTC
 *  midnight and can shift a day in negative-offset timezones). */
function dayLabel(date: string): string {
  const [y, m, d] = date.split("-").map(Number)
  if (!y || !m || !d) return date
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  })
}

function NotMeasured({ className }: { className?: string }) {
  return (
    <span
      className={cn("text-xs italic text-muted-foreground/80", className)}
      title="The provider did not report this figure. It is unknown, not zero."
    >
      not measured
    </span>
  )
}

function IntCell({ value }: { value: number | null }) {
  if (value == null) return <NotMeasured />
  return <span className="tabular-nums">{intFmt.format(value)}</span>
}

function CostCell({ value }: { value: number | null }) {
  if (value == null) return <NotMeasured />
  return <span className="tabular-nums">{formatCost(value)}</span>
}

function SimilarityCell({ value }: { value: number | null }) {
  if (value == null) return <NotMeasured />
  return <span className="tabular-nums">{value.toFixed(2)}</span>
}

/* ------------------------------------------------------------------------- *
 * Small display pieces
 * ------------------------------------------------------------------------- */

function StatTile({
  label,
  value,
}: {
  label: string
  value: number | null
}) {
  return (
    <Card className="gap-1 py-4">
      <CardHeader className="px-4">
        <CardDescription>{label}</CardDescription>
      </CardHeader>
      <CardContent className="px-4">
        {value == null ? (
          <div className="text-base font-medium italic text-muted-foreground">
            Not measured
          </div>
        ) : (
          // Proportional figures on purpose - tabular-nums makes a large
          // standalone number look loose; it is for aligned columns only.
          <div className="text-2xl font-semibold" title={intFmt.format(value)}>
            {compactFmt.format(value)}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function CostTile({ label, value }: { label: string; value: number | null }) {
  return (
    <Card className="gap-1 py-4">
      <CardHeader className="px-4">
        <CardDescription>{label}</CardDescription>
      </CardHeader>
      <CardContent className="px-4">
        {value == null ? (
          <div className="text-base font-medium italic text-muted-foreground">
            Not measured
          </div>
        ) : (
          <div className="text-2xl font-semibold">{formatCost(value)}</div>
        )}
      </CardContent>
    </Card>
  )
}

/** Tiny meter: fill and track are the same hue (chart slot 1) so the state
 *  reads across the whole bar, per the meter rule. */
function HitRateMeter({ rate }: { rate: number }) {
  const pct = Math.min(100, Math.max(0, rate * 100))
  return (
    <span className="flex items-center justify-end gap-2">
      <span
        aria-hidden="true"
        className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full"
        style={{
          background: "color-mix(in oklab, var(--chart-1) 22%, transparent)",
        }}
      >
        <span
          className="block h-full rounded-full"
          style={{ width: `${pct}%`, background: "var(--chart-1)" }}
        />
      </span>
      <span className="tabular-nums">{Math.round(pct)}%</span>
    </span>
  )
}

/* ------------------------------------------------------------------------- *
 * Sections
 * ------------------------------------------------------------------------- */

function TotalsRow({ totals }: { totals: UsageTotals }) {
  // Total spend is the two sides added, but only where BOTH are known -
  // adding a measured number to an unmeasured one would silently present a
  // partial figure as a total.
  const totalCost =
    totals.cost_usd == null && totals.embedding_cost_usd == null
      ? null
      : (totals.cost_usd ?? 0) + (totals.embedding_cost_usd ?? 0)

  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-5">
      <StatTile label="Requests" value={totals.requests} />
      <StatTile label="LLM tokens" value={totals.prompt_tokens} />
      <StatTile label="Completion tokens" value={totals.completion_tokens} />
      {/* Shown beside the LLM tokens rather than folded into them: embedding
          is usually the larger VOLUME and the smaller COST, and one combined
          number would hide both facts. */}
      <StatTile label="Embedding tokens" value={totals.embedding_tokens} />
      <CostTile label="Total cost" value={totalCost} />
    </div>
  )
}

function SpendSplit({ totals }: { totals: UsageTotals }) {
  const llm = totals.cost_usd ?? 0
  const embedding = totals.embedding_cost_usd ?? 0
  const total = llm + embedding
  if (total <= 0) return null
  const llmPct = (llm / total) * 100

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle>Where the money goes</CardTitle>
        <CardDescription>
          Answering questions versus building and searching the index. On a
          document-heavy account embedding is often the larger bill - it used
          to be invisible here.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div
          className="flex h-3 w-full overflow-hidden rounded-full bg-muted"
          role="img"
          aria-label={`Generation ${formatCost(llm)}, embedding ${formatCost(embedding)}`}
        >
          <div
            className="bg-[var(--chart-1)]"
            style={{ width: `${llmPct}%` }}
          />
          <div
            className="bg-[var(--chart-2)]"
            style={{ width: `${100 - llmPct}%` }}
          />
        </div>
        <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
          <div className="flex items-center gap-2">
            <span className="size-2.5 rounded-full bg-[var(--chart-1)]" />
            <span className="text-muted-foreground">Generation</span>
            <span className="font-medium tabular-nums">{formatCost(llm)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="size-2.5 rounded-full bg-[var(--chart-2)]" />
            <span className="text-muted-foreground">Embedding</span>
            <span className="font-medium tabular-nums">
              {formatCost(embedding)}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function CacheSavingsCard({ totals }: { totals: UsageTotals }) {
  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle>Saved by the cache</CardTitle>
        <CardDescription>
          Answers served from the L1 (exact) and L2 (semantic) caches skip the
          provider entirely - these are the tokens and money that never got
          spent.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-end gap-x-12 gap-y-4">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Cost saved
          </div>
          {totals.saved_cost_usd == null ? (
            <div className="mt-1 text-lg font-medium italic text-muted-foreground">
              Not measured
            </div>
          ) : (
            <div className="mt-1 text-4xl font-semibold text-[#006300] dark:text-[#0ca30c]">
              {formatCost(totals.saved_cost_usd)}
            </div>
          )}
        </div>
        <div>
          <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Prompt tokens saved
          </div>
          <div className="mt-1 text-xl font-semibold">
            {totals.saved_prompt_tokens == null ? (
              <NotMeasured className="text-sm" />
            ) : (
              <span title={intFmt.format(totals.saved_prompt_tokens)}>
                {compactFmt.format(totals.saved_prompt_tokens)}
              </span>
            )}
          </div>
        </div>
        <div>
          <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Completion tokens saved
          </div>
          <div className="mt-1 text-xl font-semibold">
            {totals.saved_completion_tokens == null ? (
              <NotMeasured className="text-sm" />
            ) : (
              <span title={intFmt.format(totals.saved_completion_tokens)}>
                {compactFmt.format(totals.saved_completion_tokens)}
              </span>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function CaveatsNote({ caveats }: { caveats: UsageCaveats }) {
  const n = caveats.unmeasured_requests
  return (
    <Alert>
      <Info />
      <AlertTitle>What these numbers leave out</AlertTitle>
      <AlertDescription>
        {caveats.vision_and_audio_excluded && (
          <p>
            Image captioning and audio transcription are not counted: they
            build their provider clients directly rather than going through the
            factory this meter wraps. Embedding while indexing documents{" "}
            <em>is</em> now counted.
          </p>
        )}
        {n > 0 && (
          <p>
            {intFmt.format(n)} request{n === 1 ? "" : "s"} came back without
            token usage from the provider
            {caveats.unmeasured_models.length > 0 && (
              <> ({caveats.unmeasured_models.join(", ")})</>
            )}
            . Token and cost figures exclude them - they are unmeasured, not
            zero.
          </p>
        )}
      </AlertDescription>
    </Alert>
  )
}

const requestsChartConfig = {
  requests: { label: "Requests", color: "var(--chart-1)" },
} satisfies ChartConfig

const tokensChartConfig = {
  prompt_tokens: { label: "Prompt", color: "var(--chart-1)" },
  completion_tokens: { label: "Completion", color: "var(--chart-2)" },
  saved_prompt_tokens: { label: "Saved prompt", color: "var(--chart-3)" },
  // Usually an order of magnitude larger than the others, which is itself the
  // point: on a document-heavy account the embedding line dwarfs generation.
  embedding_tokens: { label: "Embedding", color: "var(--chart-4)" },
} satisfies ChartConfig

function DailyTrends({ daily }: { daily: UsageDaily[] }) {
  const [showTable, setShowTable] = useState(false)

  // ISO dates sort lexicographically; don't trust the backend's order.
  const series = [...daily].sort((a, b) => (a.date < b.date ? -1 : 1))
  const hasTokenData = series.some(
    (d) =>
      d.prompt_tokens != null ||
      d.completion_tokens != null ||
      d.saved_prompt_tokens != null ||
      d.embedding_tokens != null
  )
  // Dots only on the short window: at 7 points they anchor the days (and keep
  // an isolated measured day between two unmeasured ones visible); at 30+ the
  // dots sit so close that their surface rings eat the line and the stroke
  // reads as dotted. Fill is the series color (recharts defaults dots to a
  // white fill) and the stroke is a 2px surface-colored ring so dots stay
  // legible where lines cross.
  const dotFor = (key: string) =>
    series.length <= 14
      ? {
          r: 3,
          fill: `var(--color-${key})`,
          stroke: "var(--card)",
          strokeWidth: 2,
        }
      : false

  const axisProps = {
    tickLine: false,
    axisLine: false,
    tickMargin: 8,
  } as const

  return (
    <div className="space-y-2">
      <div className="grid gap-3 sm:gap-4 lg:grid-cols-2">
        <Card className="gap-4">
          <CardHeader>
            <CardTitle className="text-base">Requests per day</CardTitle>
          </CardHeader>
          <CardContent>
            <ChartContainer
              config={requestsChartConfig}
              className="h-56 w-full"
            >
              <BarChart
                accessibilityLayer
                data={series}
                margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
              >
                <CartesianGrid vertical={false} />
                <XAxis
                  dataKey="date"
                  minTickGap={28}
                  tickFormatter={(value) => dayLabel(String(value))}
                  {...axisProps}
                />
                <YAxis
                  width={40}
                  allowDecimals={false}
                  tickFormatter={(value) => compactFmt.format(Number(value))}
                  {...axisProps}
                />
                <ChartTooltip
                  content={
                    <ChartTooltipContent
                      labelFormatter={(value) => dayLabel(String(value))}
                    />
                  }
                />
                {/* No entry animation: on a range switch the previous window
                    is held on screen (keepPreviousData) and replaying a
                    grow-in would read as a flash of fake change. */}
                <Bar
                  dataKey="requests"
                  fill="var(--color-requests)"
                  radius={[4, 4, 0, 0]}
                  maxBarSize={24}
                  isAnimationActive={false}
                />
              </BarChart>
            </ChartContainer>
          </CardContent>
        </Card>

        <Card className="gap-4">
          <CardHeader>
            <CardTitle className="text-base">Tokens per day</CardTitle>
            <CardDescription>
              Gaps are days the provider reported nothing - unmeasured, not
              zero.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {hasTokenData ? (
              <ChartContainer
                config={tokensChartConfig}
                className="h-56 w-full"
              >
                <LineChart
                  accessibilityLayer
                  data={series}
                  margin={{ top: 8, right: 12, left: 0, bottom: 0 }}
                >
                  <CartesianGrid vertical={false} />
                  <XAxis
                    dataKey="date"
                    minTickGap={28}
                    tickFormatter={(value) => dayLabel(String(value))}
                    {...axisProps}
                  />
                  <YAxis
                    width={40}
                    tickFormatter={(value) => compactFmt.format(Number(value))}
                    {...axisProps}
                  />
                  <ChartTooltip
                    content={
                      <ChartTooltipContent
                        labelFormatter={(value) => dayLabel(String(value))}
                      />
                    }
                  />
                  <ChartLegend content={<ChartLegendContent />} />
                  <Line
                    dataKey="prompt_tokens"
                    type="monotone"
                    stroke="var(--color-prompt_tokens)"
                    strokeWidth={2}
                    dot={dotFor("prompt_tokens")}
                    activeDot={{ r: 4 }}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                  <Line
                    dataKey="completion_tokens"
                    type="monotone"
                    stroke="var(--color-completion_tokens)"
                    strokeWidth={2}
                    dot={dotFor("completion_tokens")}
                    activeDot={{ r: 4 }}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                  <Line
                    dataKey="saved_prompt_tokens"
                    type="monotone"
                    stroke="var(--color-saved_prompt_tokens)"
                    strokeWidth={2}
                    dot={dotFor("saved_prompt_tokens")}
                    activeDot={{ r: 4 }}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                  <Line
                    dataKey="embedding_tokens"
                    type="monotone"
                    stroke="var(--color-embedding_tokens)"
                    strokeWidth={2}
                    dot={dotFor("embedding_tokens")}
                    activeDot={{ r: 4 }}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ChartContainer>
            ) : (
              <div className="flex h-56 items-center justify-center px-6 text-center text-sm text-muted-foreground">
                No token counts were reported by the provider in this window.
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* The charts' table twin - every plotted value reachable without a
          tooltip, and unmeasured days legible as such. */}
      <Button
        variant="ghost"
        size="sm"
        className="text-muted-foreground"
        onClick={() => setShowTable((v) => !v)}
      >
        {showTable ? "Hide daily table" : "View daily data as a table"}
      </Button>
      {showTable && <DailyTable series={series} />}
    </div>
  )
}

function DailyTable({ series }: { series: UsageDaily[] }) {
  const rows = [...series].reverse() // most recent first
  return (
    <Card className="gap-3 py-4">
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-6">Date</TableHead>
              <TableHead className="text-right">Requests</TableHead>
              <TableHead className="text-right">Prompt tokens</TableHead>
              <TableHead className="text-right">Completion tokens</TableHead>
              <TableHead className="text-right">Saved prompt tokens</TableHead>
              <TableHead className="pr-6 text-right">Cost</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((day) => (
              <TableRow key={day.date}>
                <TableCell className="pl-6">{dayLabel(day.date)}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {intFmt.format(day.requests)}
                </TableCell>
                <TableCell className="text-right">
                  <IntCell value={day.prompt_tokens} />
                </TableCell>
                <TableCell className="text-right">
                  <IntCell value={day.completion_tokens} />
                </TableCell>
                <TableCell className="text-right">
                  <IntCell value={day.saved_prompt_tokens} />
                </TableCell>
                <TableCell className="pr-6 text-right">
                  <CostCell value={day.cost_usd} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function ApiKeysTable({ rows }: { rows: UsageByApiKey[] }) {
  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="text-base">By API key</CardTitle>
        <CardDescription>
          Every key you have created, by what it spent. Only the prefix is
          shown - never the secret.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {rows.length === 0 ? (
          <p className="px-6 pb-2 text-sm text-muted-foreground">
            No API key activity in this window.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-6">Key</TableHead>
                <TableHead className="text-right">Requests</TableHead>
                <TableHead className="text-right">Prompt tokens</TableHead>
                <TableHead className="text-right">Completion tokens</TableHead>
                <TableHead className="pr-6 text-right">Cost</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.api_key_id}>
                  <TableCell className="pl-6">
                    <span className="font-mono text-xs">{row.key_prefix}…</span>
                    {row.revoked && (
                      <Badge variant="secondary" className="ml-2">
                        revoked
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {intFmt.format(row.requests)}
                  </TableCell>
                  <TableCell className="text-right">
                    <IntCell value={row.prompt_tokens} />
                  </TableCell>
                  <TableCell className="text-right">
                    <IntCell value={row.completion_tokens} />
                  </TableCell>
                  <TableCell className="pr-6 text-right">
                    <CostCell value={row.cost_usd} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function ModelsTable({
  rows,
  unmeasuredModels,
}: {
  rows: UsageByModel[]
  unmeasuredModels: string[]
}) {
  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="text-base">By model</CardTitle>
        <CardDescription>
          Token spend per model, across every key on this account. Embedders
          are tagged - their tokens are far cheaper than an LLM's, so the two
          are never summed into one figure.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {rows.length === 0 ? (
          <p className="px-6 pb-2 text-sm text-muted-foreground">
            No model activity in this window.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-6">Model</TableHead>
                <TableHead className="text-right">Requests</TableHead>
                <TableHead className="text-right">Prompt tokens</TableHead>
                <TableHead className="text-right">Completion tokens</TableHead>
                <TableHead className="pr-6 text-right">Cost</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={`${row.kind}:${row.model}`}>
                  <TableCell className="pl-6">
                    <span className="font-mono text-xs">{row.model}</span>
                    {row.kind === "embedding" && (
                      <Badge variant="secondary" className="ml-2">
                        embedding
                      </Badge>
                    )}
                    {unmeasuredModels.includes(row.model) && (
                      <Badge variant="outline" className="ml-2">
                        no usage reported
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {intFmt.format(row.requests)}
                  </TableCell>
                  <TableCell className="text-right">
                    <IntCell value={row.prompt_tokens} />
                  </TableCell>
                  <TableCell className="text-right">
                    <IntCell value={row.completion_tokens} />
                  </TableCell>
                  <TableCell className="pr-6 text-right">
                    <CostCell value={row.cost_usd} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function SavedTokensCell({
  prompt,
  completion,
}: {
  prompt: number | null
  completion: number | null
}) {
  if (prompt == null && completion == null) return <NotMeasured />
  return (
    <span className="tabular-nums">
      {prompt == null ? <NotMeasured /> : intFmt.format(prompt)}
      <span className="text-muted-foreground"> / </span>
      {completion == null ? <NotMeasured /> : intFmt.format(completion)}
    </span>
  )
}

function ProjectsTable({ rows }: { rows: UsageByProject[] }) {
  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="text-base">By project</CardTitle>
        <CardDescription>
          Cache performance and retrieval quality per project. Hit rate is the
          share of requests answered from the L1 or L2 cache.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {rows.length === 0 ? (
          <p className="px-6 pb-2 text-sm text-muted-foreground">
            No project activity in this window.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-6">Project</TableHead>
                <TableHead className="text-right">Requests</TableHead>
                <TableHead className="text-right">Cost</TableHead>
                <TableHead className="text-right">L1 hits</TableHead>
                <TableHead className="text-right">L2 hits</TableHead>
                <TableHead className="text-right">Misses</TableHead>
                <TableHead className="text-right">Hit rate</TableHead>
                <TableHead
                  className="text-right"
                  title="Average similarity of the chunks retrieved to answer queries"
                >
                  Avg similarity
                </TableHead>
                <TableHead
                  className="text-right"
                  title="Average similarity of questions answered from the L2 cache"
                >
                  Cache similarity
                </TableHead>
                <TableHead
                  className="pr-6 text-right"
                  title="Tokens the cache saved: prompt / completion"
                >
                  Saved (prompt / completion)
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.project_id}>
                  <TableCell className="max-w-48 truncate pl-6 font-medium">
                    {row.name}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {intFmt.format(row.requests)}
                  </TableCell>
                  <TableCell className="text-right">
                    <CostCell value={row.cost_usd} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {intFmt.format(row.cache.l1)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {intFmt.format(row.cache.l2)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {intFmt.format(row.cache.miss)}
                  </TableCell>
                  <TableCell className="text-right">
                    <HitRateMeter rate={row.cache.hit_rate} />
                  </TableCell>
                  <TableCell className="text-right">
                    <SimilarityCell value={row.avg_retrieval_similarity} />
                  </TableCell>
                  <TableCell className="text-right">
                    <SimilarityCell value={row.avg_cache_similarity} />
                  </TableCell>
                  <TableCell className="pr-6 text-right">
                    <SavedTokensCell
                      prompt={row.saved_prompt_tokens}
                      completion={row.saved_completion_tokens}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function EmptyState({ days }: { days: number }) {
  return (
    <div className="flex min-h-full flex-col">
      <Card className="my-auto py-16 text-center">
        <CardContent className="space-y-3">
          <ChartBar className="mx-auto size-10 text-muted-foreground" />
          <p className="font-medium">No API usage in the last {days} days</p>
          <p className="mx-auto max-w-md text-sm text-muted-foreground">
            Requests made with your API keys will show up here, broken down by
            model, key and project - along with what the cache saved you.
          </p>
          <p className="mx-auto max-w-md text-xs text-muted-foreground">
            Document ingestion (embedding, captioning, transcription) is not
            metered here, so ingest-only activity does not appear.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

/**
 * Pure view over one usage payload - including the "no usage at all" state.
 * Split from the SWR shell so it can be rendered directly against fixtures
 * (and so the loading/error plumbing stays in one place).
 */
export function UsageView({ data }: { data: AccountUsage }) {
  if (data.totals.requests === 0) {
    return <EmptyState days={data.window_days} />
  }
  return (
    <>
      <TotalsRow totals={data.totals} />
      <div className="grid gap-3 sm:gap-4 lg:grid-cols-2">
        <SpendSplit totals={data.totals} />
        <CacheSavingsCard totals={data.totals} />
      </div>
      <CaveatsNote caveats={data.caveats} />
      <DailyTrends daily={data.daily} />
      <ApiKeysTable rows={data.by_api_key} />
      <ModelsTable
        rows={data.by_model}
        unmeasuredModels={data.caveats.unmeasured_models}
      />
      <ProjectsTable rows={data.by_project} />
    </>
  )
}

export function UsageDashboard() {
  const [days, setDays] = useState<UsageWindow>(DEFAULT_USAGE_WINDOW)
  const { data, error, isLoading } = useSWR<AccountUsage>(
    usageKey(days),
    fetcher,
    // Hold the previous window's render while the new one loads - no skeleton
    // flash, no layout jump; the content just dims briefly (below).
    { keepPreviousData: true }
  )

  return (
    // Fixed frame like the sibling settings pages: the heading and range
    // selector never move, only the content below scrolls.
    <div className="flex h-[calc(100dvh-6.25rem)] min-h-0 flex-col gap-3 overflow-hidden sm:gap-6 md:h-full">
      <div className="flex shrink-0 flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Usage</h1>
          <p className="text-xs leading-relaxed text-muted-foreground sm:text-sm">
            Requests, tokens and cost across your API keys, models and
            projects.
          </p>
        </div>
        <Tabs
          value={String(days)}
          onValueChange={(value) => setDays(Number(value) as UsageWindow)}
        >
          <TabsList>
            {USAGE_WINDOWS.map((window) => (
              <TabsTrigger key={window} value={String(window)} className="px-3">
                {window} days
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      {/* Signed out is not a load failure - see lib/api.ts isSessionExpired. */}
      {error && !isSessionExpired(error) && (
        <p className="shrink-0 text-sm text-destructive">
          Could not load usage: {error.message}
        </p>
      )}

      {isLoading && !data && (
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pb-2 sm:space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-40" />
          <div className="grid gap-3 sm:gap-4 lg:grid-cols-2">
            <Skeleton className="h-72" />
            <Skeleton className="h-72" />
          </div>
          <Skeleton className="h-64" />
        </div>
      )}

      {data && (
        <div
          className={cn(
            "min-h-0 flex-1 space-y-4 overflow-y-auto pb-2 sm:space-y-6",
            isLoading && "opacity-60 transition-opacity"
          )}
        >
          <UsageView data={data} />
        </div>
      )}
    </div>
  )
}
