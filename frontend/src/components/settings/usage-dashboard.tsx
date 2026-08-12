"use client"

import {
  ChartBarIcon as ChartBar,
  ChartDonutIcon as ChartDonut,
  DatabaseIcon as Database,
  GaugeIcon as Gauge,
  LightningIcon as Lightning,
  PiggyBankIcon as PiggyBank,
  ReceiptIcon as Receipt,
  StackIcon as Stack,
  InfoIcon as Info,
} from "@phosphor-icons/react/dist/ssr"
import {
  type CSSProperties,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react"
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
  CardFooter,
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
  CacheTrend,
  EndpointBreakdown,
  LatencyTrend,
} from "@/components/settings/usage-monitoring"
import {
  ModelUsage,
  RetrievalQuality,
} from "@/components/settings/usage-quality"
import { TextScrambleEffect } from "@/components/ui/text-scramble-effect"
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
  USAGE_REFRESH_MS,
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

function formatPercent(value: number): string {
  return `${value.toFixed(value >= 10 ? 1 : 2)}%`
}

/** A ratio is only useful when every input is measured. This keeps frontend
 * insights from turning a provider's unknown value into an implied zero. */
function measuredSum(values: (number | null)[]): number | null {
  if (values.some((value) => value == null)) return null
  return values.reduce<number>((sum, value) => sum + (value ?? 0), 0)
}

function shareOf(value: number | null, total: number | null): number | null {
  if (value == null || total == null || total <= 0) return null
  return (value / total) * 100
}

function AnimatedValue({
  value,
  className,
  style,
}: {
  value: string
  className?: string
  style?: CSSProperties
}) {
  return (
    <span
      key={value}
      className={cn("usage-number-in inline-block", className)}
      style={style}
    >
      {value}
    </span>
  )
}

function useInViewOnce<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!node) return

    if (!("IntersectionObserver" in window)) {
      const frame = requestAnimationFrame(() => setVisible(true))
      return () => cancelAnimationFrame(frame)
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return
        setVisible(true)
        observer.disconnect()
      },
      { rootMargin: "120px 0px", threshold: 0.08 }
    )

    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return { ref, visible }
}

function MotionReveal({
  children,
  className,
  delay = 0,
}: {
  children: ReactNode
  className?: string
  delay?: number
}) {
  const { ref, visible } = useInViewOnce<HTMLDivElement>()

  return (
    <div
      ref={ref}
      data-visible={visible ? "true" : undefined}
      className={cn("usage-reveal", className)}
      style={{ "--usage-delay": `${delay}ms` } as CSSProperties}
    >
      {children}
    </div>
  )
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
  return <AnimatedValue value={intFmt.format(value)} className="tabular-nums" />
}

function CostCell({ value }: { value: number | null }) {
  if (value == null) return <NotMeasured />
  return <AnimatedValue value={formatCost(value)} className="tabular-nums" />
}

function SimilarityCell({ value }: { value: number | null }) {
  if (value == null) return <NotMeasured />
  return <AnimatedValue value={value.toFixed(2)} className="tabular-nums" />
}

/* ------------------------------------------------------------------------- *
 * Small display pieces
 * ------------------------------------------------------------------------- */

function MetricTile({
  label,
  value,
  detail,
  icon,
  accent,
  format = "number",
  className,
}: {
  label: string
  value: number | null
  detail: ReactNode
  icon: ReactNode
  accent: string
  format?: "number" | "cost"
  className?: string
}) {
  const formattedValue =
    value == null
      ? null
      : format === "cost"
        ? formatCost(value)
        : compactFmt.format(value)

  return (
    <Card
      className={cn(
        "usage-metric-card group relative gap-4 overflow-hidden py-5",
        className
      )}
    >
      <CardHeader className="grid grid-cols-[auto_1fr] items-center gap-3 px-5">
        <span
          aria-hidden="true"
          className="usage-metric-icon flex size-9 items-center justify-center rounded-lg"
          style={{ color: accent }}
        >
          {icon}
        </span>
        <CardDescription className="text-xs font-semibold tracking-[-0.01em] text-foreground/72">
          {label}
        </CardDescription>
      </CardHeader>
      <CardContent className="px-5">
        {value == null ? (
          <div className="text-base font-medium italic text-muted-foreground">
            Not measured
          </div>
        ) : (
          <div className="text-[1.75rem] font-semibold leading-none tracking-[-0.035em] sm:text-[2rem]">
            <TextScrambleEffect
              key={formattedValue}
              text={formattedValue ?? ""}
              className="tabular-nums"
            />
          </div>
        )}
      </CardContent>
      <CardFooter className="min-h-5 px-5 text-[11px] leading-relaxed text-muted-foreground">
        {detail}
      </CardFooter>
    </Card>
  )
}

/** Tiny meter: fill and track are the same hue (chart slot 1) so the state
 *  reads across the whole bar, per the meter rule. */
function HitRateMeter({
  rate,
  className,
}: {
  rate: number
  className?: string
}) {
  const pct = Math.min(100, Math.max(0, rate * 100))
  return (
    <span className={cn("flex items-center justify-end gap-2", className)}>
      <span
        aria-hidden="true"
        className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full"
        style={{
          background: "color-mix(in oklab, var(--chart-1) 22%, transparent)",
        }}
      >
        <span
          className="usage-meter-fill block h-full rounded-full"
          style={{ width: `${pct}%`, background: "var(--chart-1)" }}
        />
      </span>
      <AnimatedValue
        value={`${Math.round(pct)}%`}
        className="tabular-nums"
      />
    </span>
  )
}

/* ------------------------------------------------------------------------- *
 * Sections
 * ------------------------------------------------------------------------- */

function TotalsRow({
  totals,
  days,
}: {
  totals: UsageTotals
  days: number
}) {
  // Total spend is the two sides added, but only where BOTH are known -
  // adding a measured number to an unmeasured one would silently present a
  // partial figure as a total.
  const totalCost =
    totals.cost_usd == null && totals.embedding_cost_usd == null
      ? null
      : (totals.cost_usd ?? 0) + (totals.embedding_cost_usd ?? 0)

  const generationTokens = measuredSum([
    totals.prompt_tokens,
    totals.completion_tokens,
  ])
  const allTokens = measuredSum([
    totals.prompt_tokens,
    totals.completion_tokens,
    totals.embedding_tokens,
  ])
  const promptShare = shareOf(totals.prompt_tokens, generationTokens)
  const completionShare = shareOf(totals.completion_tokens, generationTokens)
  const embeddingShare = shareOf(totals.embedding_tokens, allTokens)
  const costPerRequest =
    totalCost != null && totals.requests > 0
      ? totalCost / totals.requests
      : null

  return (
    <div className="usage-summary-grid grid grid-cols-2 overflow-hidden rounded-2xl border border-blue-500/20 bg-blue-50/35 shadow-[0_16px_50px_-42px_rgba(37,99,235,0.55)] xl:grid-cols-5 dark:bg-blue-950/10">
      <MetricTile
        label="Requests"
        value={totals.requests}
        detail={`${compactFmt.format(totals.requests / days)} average per day`}
        icon={<Gauge className="size-4" weight="bold" />}
        accent="var(--chart-1)"
      />
      <MetricTile
        label="Prompt tokens"
        value={totals.prompt_tokens}
        detail={
          promptShare == null
            ? "Share not measured"
            : `${formatPercent(promptShare)} of generation volume`
        }
        icon={<Stack className="size-4" weight="bold" />}
        accent="var(--chart-2)"
      />
      <MetricTile
        label="Completion tokens"
        value={totals.completion_tokens}
        detail={
          completionShare == null
            ? "Share not measured"
            : `${formatPercent(completionShare)} of generation volume`
        }
        icon={<Lightning className="size-4" weight="bold" />}
        accent="var(--chart-3)"
      />
      {/* Shown beside the LLM tokens rather than folded into them: embedding
          is usually the larger VOLUME and the smaller COST, and one combined
          number would hide both facts. */}
      <MetricTile
        label="Embedding tokens"
        value={totals.embedding_tokens}
        detail={
          embeddingShare == null
            ? "Share not measured"
            : `${formatPercent(embeddingShare)} of measured tokens`
        }
        icon={<Database className="size-4" weight="bold" />}
        accent="var(--chart-4)"
      />
      <MetricTile
        label="Total cost"
        value={totalCost}
        detail={
          costPerRequest == null
            ? "Per-request cost not measured"
            : `${formatCost(costPerRequest)} average per request`
        }
        icon={<Receipt className="size-4" weight="bold" />}
        accent="var(--chart-5)"
        format="cost"
        className="col-span-2 xl:col-span-1"
      />
    </div>
  )
}

function SpendSplit({ totals }: { totals: UsageTotals }) {
  const llm = totals.cost_usd ?? 0
  const embedding = totals.embedding_cost_usd ?? 0
  const total = llm + embedding
  if (total <= 0) return null
  const hasCompleteSpend =
    totals.cost_usd != null && totals.embedding_cost_usd != null
  const llmPct = (llm / total) * 100
  const embeddingPct = 100 - llmPct
  const measuredTokens = measuredSum([
    totals.prompt_tokens,
    totals.completion_tokens,
    totals.embedding_tokens,
  ])
  const generationTokens = measuredSum([
    totals.prompt_tokens,
    totals.completion_tokens,
  ])
  const embeddingVolumePct = shareOf(totals.embedding_tokens, measuredTokens)
  const costMultiple =
    hasCompleteSpend && embedding > 0 ? llm / embedding : null
  const generationCostPerMillion =
    totals.cost_usd != null &&
    generationTokens != null &&
    generationTokens > 0
      ? (totals.cost_usd / generationTokens) * 1_000_000
      : null
  const embeddingCostPerMillion =
    totals.embedding_cost_usd != null &&
    totals.embedding_tokens != null &&
    totals.embedding_tokens > 0
      ? (totals.embedding_cost_usd / totals.embedding_tokens) * 1_000_000
      : null

  return (
    <Card className="usage-feature-card usage-spend-card gap-5 overflow-hidden">
      <CardHeader className="grid grid-cols-[1fr_auto] gap-3 border-b border-border/70 pb-5">
        <div className="flex flex-col gap-2">
          <CardTitle className="text-[17px] tracking-[-0.02em]">
            Where the money goes
          </CardTitle>
          <CardDescription>
            Generation answers questions; embedding builds and searches the
            index.
          </CardDescription>
        </div>
        <span className="text-muted-foreground">
          <ChartDonut className="size-5" weight="regular" />
        </span>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="grid items-center gap-6 sm:grid-cols-[11rem_1fr]">
          <div className="usage-donut-shell flex justify-center rounded-2xl py-3">
            <div
              className="usage-donut-in relative flex size-40 items-center justify-center rounded-full"
              style={{
                background: `conic-gradient(var(--chart-1) 0 ${llmPct}%, var(--chart-2) ${llmPct}% 100%)`,
              }}
              role="img"
              aria-label={`Generation ${formatCost(llm)}, embedding ${formatCost(embedding)}`}
            >
              <div className="flex size-28 flex-col items-center justify-center rounded-full bg-card text-center shadow-[0_0_0_1px_var(--border)]">
                <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Total spent
                </span>
                <AnimatedValue
                  value={formatCost(total)}
                  className="mt-1 text-2xl font-semibold tracking-tight"
                />
              </div>
            </div>
          </div>
          <div className="flex flex-col gap-4">
            <SpendLegendRow
              label="Generation"
              description="Prompts and model responses"
              cost={llm}
              percent={llmPct}
              color="var(--chart-1)"
            />
            <SpendLegendRow
              label="Embedding"
              description="Indexing and retrieval vectors"
              cost={embedding}
              percent={embeddingPct}
              color="var(--chart-2)"
            />
          </div>
        </div>
        <div className="usage-cost-density-grid grid grid-cols-2 gap-3 rounded-xl border bg-muted/20 p-3">
          <EfficiencyMetric
            label="Generation cost density"
            value={generationCostPerMillion}
            color="var(--chart-1)"
          />
          <EfficiencyMetric
            label="Embedding cost density"
            value={embeddingCostPerMillion}
            color="var(--chart-2)"
          />
        </div>
      </CardContent>
      <CardFooter className="border-t bg-muted/30 py-4 text-sm text-muted-foreground">
        <ChartBar className="mr-2 size-4 shrink-0" />
        {embeddingVolumePct != null && hasCompleteSpend ? (
          <span>
            Embedding produced {formatPercent(embeddingVolumePct)} of measured
            tokens but only {formatPercent(embeddingPct)} of spend
            {costMultiple != null
              ? `; generation cost ${costMultiple.toFixed(1)} times as much.`
              : "."}
          </span>
        ) : (
          <span>Token-volume comparison is not measured for this window.</span>
        )}
      </CardFooter>
    </Card>
  )
}

function EfficiencyMetric({
  label,
  value,
  color,
}: {
  label: string
  value: number | null
  color: string
}) {
  return (
    <div className="flex flex-col gap-1 py-1">
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      {value == null ? (
        <NotMeasured />
      ) : (
        <AnimatedValue
          value={`${formatCost(value)} / 1M tokens`}
          className="font-semibold tabular-nums"
          style={{ color }}
        />
      )}
    </div>
  )
}

function SpendLegendRow({
  label,
  description,
  cost,
  percent,
  color,
}: {
  label: string
  description: string
  cost: number
  percent: number
  color: string
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className="mt-1 size-2.5 shrink-0 rounded-full"
            style={{ background: color }}
          />
          <div>
            <div className="font-medium">{label}</div>
            <div className="text-xs text-muted-foreground">{description}</div>
          </div>
        </div>
        <div className="text-right">
          <AnimatedValue
            value={formatCost(cost)}
            className="font-semibold tabular-nums"
          />
          <AnimatedValue
            value={formatPercent(percent)}
            className="block text-xs text-muted-foreground tabular-nums"
          />
        </div>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className="usage-meter-fill h-full rounded-full"
          style={{ width: `${percent}%`, background: color }}
        />
      </div>
    </div>
  )
}

function CacheSavingsCard({ totals }: { totals: UsageTotals }) {
  const savedGenerationTokens = measuredSum([
    totals.saved_prompt_tokens,
    totals.saved_completion_tokens,
  ])
  const potentialGenerationTokens = measuredSum([
    totals.prompt_tokens,
    totals.completion_tokens,
    totals.saved_prompt_tokens,
    totals.saved_completion_tokens,
  ])
  const tokenSavingsPct = shareOf(
    savedGenerationTokens,
    potentialGenerationTokens
  )
  const potentialGenerationCost = measuredSum([
    totals.cost_usd,
    totals.saved_cost_usd,
  ])
  const costSavingsPct = shareOf(
    totals.saved_cost_usd,
    potentialGenerationCost
  )

  return (
    <Card className="usage-feature-card usage-savings-card gap-5 overflow-hidden">
      <CardHeader className="grid grid-cols-[1fr_auto] gap-3 border-b border-border/70 pb-5">
        <div className="flex flex-col gap-2">
          <CardTitle className="text-[17px] tracking-[-0.02em]">
            Saved by the cache
          </CardTitle>
          <CardDescription>
            L1 and L2 cache hits skip provider generation, avoiding tokens and
            cost.
          </CardDescription>
        </div>
        <span className="text-muted-foreground">
          <PiggyBank className="size-5" weight="regular" />
        </span>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="usage-savings-hero flex flex-col gap-4 rounded-2xl border p-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Generation tokens avoided
              </div>
              {tokenSavingsPct == null ? (
                <div className="mt-1 text-lg font-medium italic text-muted-foreground">
                  Not measured
                </div>
              ) : (
                <AnimatedValue
                  value={formatPercent(tokenSavingsPct)}
                  className="mt-1 text-4xl font-semibold tracking-tight"
                  style={{ color: "var(--chart-3)" }}
                />
              )}
            </div>
            <div className="text-right text-xs text-muted-foreground">
              {savedGenerationTokens == null ? (
                <NotMeasured />
              ) : (
                <>
                  <AnimatedValue
                    value={compactFmt.format(savedGenerationTokens)}
                    className="block text-base font-semibold text-foreground"
                  />
                  of potential generation volume
                </>
              )}
            </div>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="usage-meter-fill h-full rounded-full"
              style={{
                width: `${tokenSavingsPct ?? 0}%`,
                background: "var(--chart-3)",
              }}
            />
          </div>
        </div>
        <div className="usage-savings-metrics grid grid-cols-2 gap-3 rounded-xl border bg-card/70 p-3 sm:grid-cols-3">
          <SavingsMetric
            label="Cost saved"
            value={
              totals.saved_cost_usd == null
                ? null
                : formatCost(totals.saved_cost_usd)
            }
            detail={
              costSavingsPct == null
                ? "Reduction not measured"
                : `${formatPercent(costSavingsPct)} of potential generation cost`
            }
          />
          <SavingsMetric
            label="Prompt saved"
            value={
              totals.saved_prompt_tokens == null
                ? null
                : compactFmt.format(totals.saved_prompt_tokens)
            }
            detail="tokens avoided"
          />
          <SavingsMetric
            label="Completion saved"
            value={
              totals.saved_completion_tokens == null
                ? null
                : compactFmt.format(totals.saved_completion_tokens)
            }
            detail="tokens avoided"
            className="col-span-2 sm:col-span-1"
          />
        </div>
      </CardContent>
      <CardFooter className="flex-col items-start gap-2 border-t bg-muted/30 py-4">
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 font-medium">
            <Database className="size-4 text-muted-foreground" />
            Dimension archive recovery
          </div>
          <div className="flex items-baseline gap-2">
            {totals.saved_embedding_tokens == null ? (
              <NotMeasured />
            ) : (
              <AnimatedValue
                value={`${compactFmt.format(totals.saved_embedding_tokens)} tokens`}
                className="font-semibold"
              />
            )}
            {totals.saved_embedding_cost_usd != null && (
              <Badge variant="secondary">
                {formatCost(totals.saved_embedding_cost_usd)} avoided
              </Badge>
            )}
          </div>
        </div>
        <CardDescription>
          Full-width vectors were restored from the archive instead of being
          re-embedded.
        </CardDescription>
      </CardFooter>
    </Card>
  )
}

function SavingsMetric({
  label,
  value,
  detail,
  className,
}: {
  label: string
  value: string | null
  detail: string
  className?: string
}) {
  return (
    <div className={cn("flex flex-col gap-1 py-1", className)}>
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      {value == null ? (
        <NotMeasured />
      ) : (
        <AnimatedValue
          value={value}
          className="text-xl font-semibold tracking-tight"
        />
      )}
      <div className="text-xs leading-relaxed text-muted-foreground">
        {detail}
      </div>
    </div>
  )
}

function CaveatsNote({ caveats }: { caveats: UsageCaveats }) {
  const n = caveats.unmeasured_requests
  return (
    <Alert className="usage-caveat border-blue-500/20 bg-blue-50/45 py-3.5 dark:bg-blue-950/15">
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
  const { ref: trendsRef, visible: trendsVisible } =
    useInViewOnce<HTMLDivElement>()

  // ISO dates sort lexicographically; don't trust the backend's order.
  const series = [...daily].sort((a, b) => (a.date < b.date ? -1 : 1))
  const hasTokenData = series.some(
    (d) =>
      d.prompt_tokens != null ||
      d.completion_tokens != null ||
      d.saved_prompt_tokens != null ||
      d.embedding_tokens != null
  )
  // Remounts the charts when the WINDOW changes (7 -> 30 -> 90) so the entry
  // animation replays, while leaving them mounted across an in-place refresh -
  // the five-minute poll must not restart the animation under the reader.
  const seriesKey = `${series[0]?.date ?? "empty"}:${series.at(-1)?.date ?? "empty"}`
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
    <div ref={trendsRef} className="flex flex-col gap-3">
      <div className="grid gap-3 sm:gap-4 lg:grid-cols-2">
        <Card className="usage-chart-card gap-4 overflow-hidden">
          <CardHeader className="border-b border-border/70 bg-muted/15 pb-5">
            <CardTitle className="flex items-center gap-2 text-base">
              <ChartBar className="size-4 text-muted-foreground" />
              Requests per day
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ChartContainer
              config={requestsChartConfig}
              className="h-56 w-full"
            >
              <BarChart
                key={`requests:${seriesKey}:${trendsVisible}`}
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
                <Bar
                  dataKey="requests"
                  fill="var(--color-requests)"
                  radius={[4, 4, 0, 0]}
                  maxBarSize={24}
                  isAnimationActive={trendsVisible}
                  animationBegin={80}
                  animationDuration={700}
                  animationEasing="ease-out"
                />
              </BarChart>
            </ChartContainer>
          </CardContent>
        </Card>

        <Card className="usage-chart-card gap-4 overflow-hidden">
          <CardHeader className="border-b border-border/70 bg-muted/15 pb-5">
            <CardTitle className="flex items-center gap-2 text-base">
              <Stack className="size-4 text-muted-foreground" />
              Tokens per day
            </CardTitle>
          </CardHeader>
          <CardContent>
            {hasTokenData ? (
              <ChartContainer
                config={tokensChartConfig}
                className="h-56 w-full"
              >
                <LineChart
                  key={`tokens:${seriesKey}:${trendsVisible}`}
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
                    isAnimationActive={trendsVisible}
                    animationBegin={100}
                    animationDuration={720}
                    animationEasing="ease-out"
                  />
                  <Line
                    dataKey="completion_tokens"
                    type="monotone"
                    stroke="var(--color-completion_tokens)"
                    strokeWidth={2}
                    dot={dotFor("completion_tokens")}
                    activeDot={{ r: 4 }}
                    connectNulls={false}
                    isAnimationActive={trendsVisible}
                    animationBegin={160}
                    animationDuration={720}
                    animationEasing="ease-out"
                  />
                  <Line
                    dataKey="saved_prompt_tokens"
                    type="monotone"
                    stroke="var(--color-saved_prompt_tokens)"
                    strokeWidth={2}
                    dot={dotFor("saved_prompt_tokens")}
                    activeDot={{ r: 4 }}
                    connectNulls={false}
                    isAnimationActive={trendsVisible}
                    animationBegin={220}
                    animationDuration={720}
                    animationEasing="ease-out"
                  />
                  <Line
                    dataKey="embedding_tokens"
                    type="monotone"
                    stroke="var(--color-embedding_tokens)"
                    strokeWidth={2}
                    dot={dotFor("embedding_tokens")}
                    activeDot={{ r: 4 }}
                    connectNulls={false}
                    isAnimationActive={trendsVisible}
                    animationBegin={280}
                    animationDuration={720}
                    animationEasing="ease-out"
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
      {showTable && (
        <div className="usage-enter">
          <DailyTable series={series} />
        </div>
      )}
    </div>
  )
}

function DailyTable({ series }: { series: UsageDaily[] }) {
  const rows = [...series].reverse() // most recent first
  return (
    <Card className="usage-daily-table h-[32rem] gap-0 overflow-hidden py-0 md:h-[24rem]">
      <CardContent className="min-h-0 flex-1 overflow-y-auto p-0">
        <div className="divide-y md:hidden">
          {rows.map((day) => (
            <div
              key={`${day.date}:mobile`}
              className="flex flex-col gap-4 px-4 py-5"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="font-medium">{dayLabel(day.date)}</div>
                <MobileDatum label="Cost" className="shrink-0 text-right">
                  <CostCell value={day.cost_usd} />
                </MobileDatum>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-4">
                <MobileDatum label="Requests">
                  <AnimatedValue
                    value={intFmt.format(day.requests)}
                    className="tabular-nums"
                  />
                </MobileDatum>
                <MobileDatum label="Prompt tokens">
                  <IntCell value={day.prompt_tokens} />
                </MobileDatum>
                <MobileDatum label="Completion tokens">
                  <IntCell value={day.completion_tokens} />
                </MobileDatum>
                <MobileDatum label="Saved prompt tokens">
                  <IntCell value={day.saved_prompt_tokens} />
                </MobileDatum>
              </div>
            </div>
          ))}
        </div>
        <div className="hidden md:block">
          <Table>
            <TableHeader className="sticky top-0 bg-muted">
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
                    <AnimatedValue value={intFmt.format(day.requests)} />
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
        </div>
      </CardContent>
    </Card>
  )
}

const INITIAL_TABLE_ROWS = 3

function TableDisclosure({
  expanded,
  total,
  onToggle,
}: {
  expanded: boolean
  total: number
  onToggle: () => void
}) {
  if (total <= INITIAL_TABLE_ROWS) return null

  return (
    <CardFooter className="usage-table-footer shrink-0 justify-between gap-3 border-t bg-card py-3">
      <span className="text-xs text-muted-foreground">
        Showing {expanded ? total : INITIAL_TABLE_ROWS} of {total}
      </span>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-expanded={expanded}
        onClick={onToggle}
      >
        {expanded ? "Show top 3" : "View all"}
      </Button>
    </CardFooter>
  )
}

function ApiKeysTable({ rows }: { rows: UsageByApiKey[] }) {
  const [expanded, setExpanded] = useState(false)
  const visibleRows = expanded ? rows : rows.slice(0, INITIAL_TABLE_ROWS)

  return (
    <Card
      className={cn(
        "usage-data-card gap-0 overflow-hidden",
        rows.length > 0 && "h-[34rem] md:h-[27rem]"
      )}
    >
      <CardHeader className="shrink-0 border-b bg-muted/20 pb-5">
        <CardTitle className="flex items-center gap-2 text-base">
          <Receipt className="size-4 text-muted-foreground" />
          By API key
        </CardTitle>
        <CardDescription>
          Every key you have created, by what it spent. Only the prefix is
          shown - never the secret.
        </CardDescription>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 overflow-y-auto p-0">
        {rows.length === 0 ? (
          <p className="px-6 pb-2 text-sm text-muted-foreground">
            No API key activity in this window.
          </p>
        ) : (
          <>
            <div className="divide-y md:hidden">
              {visibleRows.map((row) => (
                <div
                  key={`${row.api_key_id}:mobile`}
                  className="flex flex-col gap-4 px-4 py-5"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="break-all font-mono text-sm font-medium">
                        {row.key_prefix}&hellip;
                      </div>
                      {row.revoked && (
                        <Badge variant="secondary" className="mt-2">
                          revoked
                        </Badge>
                      )}
                    </div>
                    <MobileDatum label="Cost" className="shrink-0 text-right">
                      <CostCell value={row.cost_usd} />
                    </MobileDatum>
                  </div>
                  <div className="grid grid-cols-3 gap-3">
                    <MobileDatum label="Requests">
                      <AnimatedValue
                        value={intFmt.format(row.requests)}
                        className="tabular-nums"
                      />
                    </MobileDatum>
                    <MobileDatum label="Prompt">
                      <IntCell value={row.prompt_tokens} />
                    </MobileDatum>
                    <MobileDatum label="Completion">
                      <IntCell value={row.completion_tokens} />
                    </MobileDatum>
                  </div>
                </div>
              ))}
            </div>
            <div className="hidden md:block">
              <Table>
            <TableHeader className="sticky top-0 bg-muted">
              <TableRow>
                <TableHead className="pl-6">Key</TableHead>
                <TableHead className="text-right">Requests</TableHead>
                <TableHead className="text-right">Prompt tokens</TableHead>
                <TableHead className="text-right">Completion tokens</TableHead>
                <TableHead className="pr-6 text-right">Cost</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleRows.map((row) => (
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
                    <AnimatedValue value={intFmt.format(row.requests)} />
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
            </div>
          </>
        )}
      </CardContent>
      <TableDisclosure
        expanded={expanded}
        total={rows.length}
        onToggle={() => setExpanded((value) => !value)}
      />
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
  const [expanded, setExpanded] = useState(false)
  const visibleRows = expanded ? rows : rows.slice(0, INITIAL_TABLE_ROWS)

  return (
    <Card
      className={cn(
        "usage-data-card gap-0 overflow-hidden",
        rows.length > 0 && "h-[34rem] md:h-[27rem]"
      )}
    >
      <CardHeader className="shrink-0 border-b bg-muted/20 pb-5">
        <CardTitle className="flex items-center gap-2 text-base">
          <Stack className="size-4 text-muted-foreground" />
          By model
        </CardTitle>
        <CardDescription>
          Token spend per model, across every key on this account. Embedders
          are tagged - their tokens are far cheaper than an LLM&apos;s, so the two
          are never summed into one figure.
        </CardDescription>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 overflow-y-auto p-0">
        {rows.length === 0 ? (
          <p className="px-6 pb-2 text-sm text-muted-foreground">
            No model activity in this window.
          </p>
        ) : (
          <>
            <div className="divide-y md:hidden">
              {visibleRows.map((row) => (
                <div
                  key={`${row.kind}:${row.model}:mobile`}
                  className="flex flex-col gap-4 px-4 py-5"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="break-all font-mono text-sm font-medium">
                        {row.model}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {row.kind === "embedding" && (
                          <Badge variant="secondary">embedding</Badge>
                        )}
                        {unmeasuredModels.includes(row.model) && (
                          <Badge variant="outline">no usage reported</Badge>
                        )}
                      </div>
                    </div>
                    <MobileDatum label="Cost" className="shrink-0 text-right">
                      <CostCell value={row.cost_usd} />
                    </MobileDatum>
                  </div>
                  <div className="grid grid-cols-3 gap-3">
                    <MobileDatum label="Requests">
                      <AnimatedValue
                        value={intFmt.format(row.requests)}
                        className="tabular-nums"
                      />
                    </MobileDatum>
                    <MobileDatum label="Prompt">
                      <IntCell value={row.prompt_tokens} />
                    </MobileDatum>
                    <MobileDatum label="Completion">
                      <IntCell value={row.completion_tokens} />
                    </MobileDatum>
                  </div>
                </div>
              ))}
            </div>
            <div className="hidden md:block">
              <Table>
                <TableHeader className="sticky top-0 bg-muted">
                  <TableRow>
                    <TableHead className="pl-6">Model</TableHead>
                    <TableHead className="text-right">Requests</TableHead>
                    <TableHead className="text-right">Prompt tokens</TableHead>
                    <TableHead className="text-right">Completion tokens</TableHead>
                    <TableHead className="pr-6 text-right">Cost</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleRows.map((row) => (
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
                        <AnimatedValue value={intFmt.format(row.requests)} />
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
            </div>
          </>
        )}
      </CardContent>
      <TableDisclosure
        expanded={expanded}
        total={rows.length}
        onToggle={() => setExpanded((value) => !value)}
      />
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
      {prompt == null ? (
        <NotMeasured />
      ) : (
        <AnimatedValue value={intFmt.format(prompt)} />
      )}
      <span className="text-muted-foreground"> / </span>
      {completion == null ? (
        <NotMeasured />
      ) : (
        <AnimatedValue value={intFmt.format(completion)} />
      )}
    </span>
  )
}

function MobileDatum({
  label,
  children,
  className,
}: {
  label: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-sm font-medium">{children}</div>
    </div>
  )
}

function ProjectsTable({ rows }: { rows: UsageByProject[] }) {
  const [expanded, setExpanded] = useState(false)
  const visibleRows = expanded ? rows : rows.slice(0, INITIAL_TABLE_ROWS)

  return (
    <Card
      className={cn(
        "usage-data-card gap-0 overflow-hidden",
        rows.length > 0 && "h-[38rem] md:h-[27rem]"
      )}
    >
      <CardHeader className="shrink-0 border-b bg-muted/20 pb-5">
        <CardTitle className="flex items-center gap-2 text-base">
          <Database className="size-4 text-muted-foreground" />
          By project
        </CardTitle>
        <CardDescription>
          Cache performance and retrieval quality per project. Hit rate is the
          share of requests answered from the L1 or L2 cache.
        </CardDescription>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 overflow-y-auto p-0">
        {rows.length === 0 ? (
          <p className="px-6 pb-2 text-sm text-muted-foreground">
            No project activity in this window.
          </p>
        ) : (
          <>
            <div className="divide-y md:hidden">
              {visibleRows.map((row) => (
                <div
                  key={`${row.project_id}:mobile`}
                  className="flex flex-col gap-4 px-4 py-5"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="break-words font-medium">{row.name}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        <AnimatedValue
                          value={`${intFmt.format(row.requests)} requests`}
                        />
                      </div>
                    </div>
                    <MobileDatum label="Cost" className="shrink-0 text-right">
                      <CostCell value={row.cost_usd} />
                    </MobileDatum>
                  </div>
                  <div className="grid grid-cols-3 gap-x-3 gap-y-4">
                    <MobileDatum label="L1 hits">
                      <AnimatedValue
                        value={intFmt.format(row.cache.l1)}
                        className="tabular-nums"
                      />
                    </MobileDatum>
                    <MobileDatum label="L2 hits">
                      <AnimatedValue
                        value={intFmt.format(row.cache.l2)}
                        className="tabular-nums"
                      />
                    </MobileDatum>
                    <MobileDatum label="Misses">
                      <AnimatedValue
                        value={intFmt.format(row.cache.miss)}
                        className="tabular-nums"
                      />
                    </MobileDatum>
                    <MobileDatum label="Retrieval similarity">
                      <SimilarityCell value={row.avg_retrieval_similarity} />
                    </MobileDatum>
                    <MobileDatum label="Cache similarity">
                      <span
                        title={
                          row.avg_cache_similarity == null && row.cache.l2 > 0
                            ? "This project's L2 hits predate similarity recording - newer hits will show a score."
                            : undefined
                        }
                      >
                        <SimilarityCell value={row.avg_cache_similarity} />
                      </span>
                    </MobileDatum>
                    <MobileDatum label="Hit rate">
                      <HitRateMeter
                        rate={row.cache.hit_rate}
                        className="justify-start"
                      />
                    </MobileDatum>
                    <MobileDatum
                      label="Saved tokens (prompt / completion)"
                      className="col-span-3"
                    >
                      <SavedTokensCell
                        prompt={row.saved_prompt_tokens}
                        completion={row.saved_completion_tokens}
                      />
                    </MobileDatum>
                  </div>
                </div>
              ))}
            </div>
            <div className="hidden md:block">
              <Table>
                <TableHeader className="sticky top-0 bg-muted">
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
                  {visibleRows.map((row) => (
                    <TableRow key={row.project_id}>
                      <TableCell className="max-w-48 truncate pl-6 font-medium">
                        {row.name}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        <AnimatedValue value={intFmt.format(row.requests)} />
                      </TableCell>
                      <TableCell className="text-right">
                        <CostCell value={row.cost_usd} />
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        <AnimatedValue value={intFmt.format(row.cache.l1)} />
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        <AnimatedValue value={intFmt.format(row.cache.l2)} />
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        <AnimatedValue value={intFmt.format(row.cache.miss)} />
                      </TableCell>
                      <TableCell className="text-right">
                        <HitRateMeter rate={row.cache.hit_rate} />
                      </TableCell>
                      <TableCell className="text-right">
                        <SimilarityCell value={row.avg_retrieval_similarity} />
                      </TableCell>
                      <TableCell
                        className="text-right"
                        title={
                          row.avg_cache_similarity == null && row.cache.l2 > 0
                            ? "This project's L2 hits predate similarity recording - newer hits will show a score."
                            : undefined
                        }
                      >
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
            </div>
          </>
        )}
      </CardContent>
      <TableDisclosure
        expanded={expanded}
        total={rows.length}
        onToggle={() => setExpanded((value) => !value)}
      />
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
    <div className="usage-dashboard-content usage-motion flex min-h-full flex-col gap-6 sm:gap-8">
      <MotionReveal>
        <TotalsRow totals={data.totals} days={data.window_days} />
      </MotionReveal>
      <MotionReveal delay={60}>
        <div className="grid gap-4 lg:grid-cols-2">
          <SpendSplit totals={data.totals} />
          <CacheSavingsCard totals={data.totals} />
        </div>
      </MotionReveal>
      <MotionReveal delay={80}>
        <CaveatsNote caveats={data.caveats} />
      </MotionReveal>
      <MotionReveal delay={90}>
        <section className="flex flex-col gap-4" aria-labelledby="usage-activity-heading">
          <div className="usage-section-heading">
            <div>
              <h2 id="usage-activity-heading">Activity over time</h2>
              <p>Traffic, token volume and delivery performance across the selected window.</p>
            </div>
          </div>
          <DailyTrends daily={data.daily} />
        </section>
      </MotionReveal>
      <MotionReveal delay={70}>
        <section className="flex flex-col gap-4" aria-labelledby="usage-operations-heading">
          <div className="usage-section-heading">
            <div>
              <h2 id="usage-operations-heading">Operational performance</h2>
              <p>Latency, endpoint demand, cache behavior and retrieval quality.</p>
            </div>
          </div>
          {/* Operational half: how the system BEHAVED, next to what it spent. */}
          <LatencyTrend daily={data.daily} />
          <div className="grid gap-4 lg:grid-cols-2">
            <EndpointBreakdown rows={data.by_endpoint} />
            <CacheTrend daily={data.daily} />
          </div>
          <ModelUsage rows={data.by_model} />
          <RetrievalQuality daily={data.daily} />
        </section>
      </MotionReveal>
      <MotionReveal delay={70}>
        <section className="flex flex-col gap-4" aria-labelledby="usage-allocation-heading">
          <div className="usage-section-heading">
            <div>
              <h2 id="usage-allocation-heading">Allocation &amp; governance</h2>
              <p>Trace account consumption across credentials, models and projects.</p>
            </div>
          </div>
          <ApiKeysTable rows={data.by_api_key} />
          <ModelsTable
            rows={data.by_model}
            unmeasuredModels={data.caveats.unmeasured_models}
          />
          <ProjectsTable rows={data.by_project} />
        </section>
      </MotionReveal>
    </div>
  )
}

export function UsageDashboard() {
  const [days, setDays] = useState<UsageWindow>(DEFAULT_USAGE_WINDOW)
  const { data, error, isLoading } = useSWR<AccountUsage>(
    usageKey(days),
    fetcher,
    {
      // Hold the previous window's render while the new one loads - no skeleton
      // flash, no layout jump; the content just dims briefly (below).
      keepPreviousData: true,
      // Poll the window actually on screen. The sidebar polls the default one
      // wherever the user is; this covers 7 and 90 while they are selected.
      refreshInterval: USAGE_REFRESH_MS,
    }
  )

  return (
    // Fixed frame like the sibling settings pages: the heading and range
    // selector never move, only the content below scrolls.
    <div className="usage-dashboard flex h-[calc(100dvh-6.25rem)] min-h-0 flex-col gap-4 overflow-hidden md:h-full">
      <div className="usage-dashboard-header flex shrink-0 flex-wrap items-center justify-between gap-4 border-b border-border/70 pb-4 sm:pb-5">
        <div>
          <h1 className="text-[1.75rem] font-semibold leading-tight tracking-[-0.035em]">Usage</h1>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground sm:text-sm">
            Requests, tokens and cost across your API keys, models and
            projects.
          </p>
        </div>
        <Tabs
          value={String(days)}
          onValueChange={(value) => setDays(Number(value) as UsageWindow)}
        >
          <TabsList className="h-10 rounded-xl border border-border/80 bg-muted/60 p-1 shadow-sm">
            {USAGE_WINDOWS.map((window) => (
              <TabsTrigger key={window} value={String(window)} className="rounded-lg px-3.5 text-xs font-semibold data-[state=active]:shadow-sm">
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
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pb-2 sm:gap-6">
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
            "usage-scroll min-h-0 flex-1 overflow-y-auto pb-3 pr-0.5",
            isLoading && "opacity-60 transition-opacity"
          )}
        >
          <UsageView data={data} />
        </div>
      )}
    </div>
  )
}
