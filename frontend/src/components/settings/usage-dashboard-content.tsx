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
import {
  CacheTrend,
  EndpointBreakdown,
  LatencyTrend,
} from "@/components/settings/usage-monitoring"
import {
  ModelUsage,
  RetrievalQuality,
} from "@/components/settings/usage-quality"
import { ProjectPortfolio } from "@/components/settings/usage-projects"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
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
import { DeferredUsagePanel } from "@/components/settings/usage-deferred-panel"

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
  // A real charge must never PRINT as zero. Four fixed places was not enough:
  // a 200-token gpt-4o-mini call costs $0.0000366 and rendered as "$0.0000",
  // and a small embedding as "$0.0000" too - the same misleading zero the
  // backend's NULL-is-not-zero rule exists to prevent, reintroduced in the
  // formatter. Below $0.0001 the precision follows the magnitude instead, so
  // the first two significant digits always survive.
  if (abs > 0 && abs < 0.0001) {
    // Below ~5e-11 no fixed-point rendering keeps a significant digit, so the
    // representation changes rather than the precision - a capped toFixed(10)
    // printed "$0.0000000000", the very thing the paragraph above forbids.
    // Unreachable from a stored cost (quantised to 1e-10) but not from a
    // derived one such as cost-per-request.
    if (abs < 1e-9) return `${value < 0 ? "-" : ""}<$0.000000001`
    const places = Math.ceil(-Math.log10(abs)) + 2
    return `$${value.toFixed(places)}`
  }
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

/** What one side of the spend split actually is.
 *
 * A NULL cost has four causes and they are not interchangeable: nothing of this
 * kind ran; it ran and the provider reported no tokens; it ran and was measured
 * but no price is listed; or it ran, was measured and was priced. The backend
 * spends eight lines of comment keeping those apart (services/usage_report.py)
 * and the dashboard used to collapse them again in four places at once - the
 * headline tile, both legend rows, the donut geometry and its aria-label -
 * which is how one card came to say "(partial)", "Not measured" and "this LLM
 * has no published rate" simultaneously.
 *
 * Derived once here and passed down, so the four places cannot drift apart. */
type SideSpend =
  | { kind: "priced"; cost: number }
  | { kind: "unpriced" }
  | { kind: "unmeasured" }
  | { kind: "absent" }

function sideSpend(
  cost: number | null,
  tokens: (number | null)[],
  ranUnmeasured: boolean
): SideSpend {
  if (cost != null) return { kind: "priced", cost }
  // Any measured token count proves it ran, so `??  0` is safe here in a way
  // measuredSum is not: measuredSum returns null when EITHER input is null,
  // which turned "half measured" into "did not happen".
  if (tokens.some((value) => (value ?? 0) > 0)) return { kind: "unpriced" }
  return ranUnmeasured ? { kind: "unmeasured" } : { kind: "absent" }
}

/** Why a side contributes no dollars. Empty for a priced side, which the
 *  callers below never ask about - but TypeScript cannot know that a priced
 *  LLM implies an unpriced embedder, so the narrowing is made explicit here
 *  rather than asserted at four call sites. */
function sideReason(side: SideSpend): string {
  return side.kind === "priced" ? "" : SIDE_LABEL[side.kind][1]
}

const SIDE_LABEL: Record<Exclude<SideSpend["kind"], "priced">, [string, string]> = {
  unpriced: ["Not priced", "no public rate for this model"],
  unmeasured: ["Not measured", "the provider reported no usage"],
  absent: ["None", "nothing of this kind ran"],
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
            <span className="tabular-nums">{formattedValue}</span>
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
  caveats,
}: {
  totals: UsageTotals
  days: number
  caveats: UsageCaveats
}) {
  // Total spend is the two sides added, but only where BOTH are known -
  // adding a measured number to an unmeasured one would silently present a
  // partial figure as a total.
  //
  // The guard used to be an AND, which meant it only fired when BOTH sides
  // were unmeasured - so exactly the case it was written to prevent, one side
  // known and one NULL, fell through to `?? 0` and rendered a partial figure
  // as the total.
  //
  // But blanking the tile is the wrong correction, because only three OpenAI
  // embedding models have a listed price: an account on Gemini, Cohere or a
  // local embedder has a NULL embedding cost permanently, and would have seen
  // "Not measured" in place of a fully measured LLM bill - while the card
  // directly below still rendered that same figure. So: show the combined
  // number when both sides are priced, otherwise show the side that IS
  // measured and say which one it is. Never add a measured number to an
  // unmeasured one and call the result a total.
  const ranUnmeasured = (caveats.unmeasured_models ?? []).length > 0
  const llmSpend = sideSpend(
    totals.cost_usd,
    [totals.prompt_tokens, totals.completion_tokens],
    ranUnmeasured
  )
  const embedSpend = sideSpend(
    totals.embedding_cost_usd,
    [totals.embedding_tokens],
    false
  )
  const spendComplete =
    llmSpend.kind === "priced" && embedSpend.kind === "priced"
  // Only a side that is priced contributes. Never add a measured number to an
  // unmeasured one and call the result a total - but never blank a measured
  // side either, which is what routing both through measuredSum did: only 3 of
  // the catalog's 22 embedders have a listed price, so "embedding is unpriced"
  // is the ordinary state, not an edge, and it was hiding real LLM spend.
  const pricedSides = [llmSpend, embedSpend].filter(
    (side): side is { kind: "priced"; cost: number } => side.kind === "priced"
  )
  const totalCost = pricedSides.length
    ? pricedSides.reduce((sum, side) => sum + side.cost, 0)
    : null
  // Says what is missing and WHY, without asserting a price gap for a side
  // that never ran.
  const partialSpendNote = spendComplete
    ? null
    : totalCost == null
      ? "Nothing in this window has a published rate"
      : llmSpend.kind === "priced"
        ? `Generation only - embedding ${sideReason(embedSpend)}`
        : `Embedding only - generation ${sideReason(llmSpend)}`

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
  const potentialGenerationCost = measuredSum([
    totals.cost_usd,
    totals.saved_cost_usd,
  ])
  const costAvoidedShare = shareOf(
    totals.saved_cost_usd,
    potentialGenerationCost
  )

  return (
    <div className="usage-summary-grid grid grid-cols-2 overflow-hidden rounded-2xl border border-border bg-card shadow-sm xl:grid-cols-6">
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
        // "Estimated", not "Total". Every key here is the customer's own, so
        // this figure is tokens x the PUBLIC LIST PRICE recorded in
        // providers/registry.py - it cannot know their actual rate, which
        // moves with free tiers, committed-use discounts, Azure deployment
        // types and OpenRouter's markup. Calling a list-price estimate the
        // "total cost" is what made the number read as a bill it never was.
        label={
          spendComplete
            ? "Estimated cost"
            : totalCost == null
              ? "Estimated cost"
              : "Estimated cost (partial)"
        }
        value={totalCost}
        detail={
          partialSpendNote ??
          (costPerRequest == null
            ? "Per-request cost not measured"
            : `${formatCost(costPerRequest)} per request, at list prices`)
        }
        icon={<Receipt className="size-4" weight="bold" />}
        accent="var(--chart-5)"
        format="cost"
      />
      <MetricTile
        label="Cost avoided"
        value={totals.saved_cost_usd}
        detail={
          costAvoidedShare == null
            ? "Savings rate not measured"
            : `${formatPercent(costAvoidedShare)} of potential generation cost`
        }
        icon={<PiggyBank className="size-4" weight="bold" />}
        accent="var(--chart-3)"
        format="cost"
      />
    </div>
  )
}

function SpendSplit({
  totals,
  caveats,
}: {
  totals: UsageTotals
  caveats: UsageCaveats
}) {
  const llmSpend = sideSpend(
    totals.cost_usd,
    [totals.prompt_tokens, totals.completion_tokens],
    (caveats.unmeasured_models ?? []).length > 0
  )
  const embedSpend = sideSpend(
    totals.embedding_cost_usd,
    [totals.embedding_tokens],
    false
  )
  const llm = totals.cost_usd ?? 0
  const embedding = totals.embedding_cost_usd ?? 0
  const total = llm + embedding
  if (total <= 0) return null
  const hasCompleteSpend =
    llmSpend.kind === "priced" && embedSpend.kind === "priced"
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
      <CardContent className="flex flex-col gap-6">
        <div className="grid items-center gap-6 sm:grid-cols-[11rem_1fr]">
          <div className="flex justify-center py-1">
            <div
              className="usage-donut-in relative flex size-40 items-center justify-center rounded-full"
              style={{
                background: hasCompleteSpend
                  ? `conic-gradient(var(--chart-1) 0 ${llmPct}%, var(--chart-2) ${llmPct}% 100%)`
                  // One side unpriced: paint the measured side only rather
                  // than a 100/0 ring that reads as a real split.
                  : `conic-gradient(${
                      llmSpend.kind === "priced"
                        ? "var(--chart-1)"
                        : "var(--chart-2)"
                    } 0 100%)`,
              }}
              role="img"
              // Built from the nullable values, not the `?? 0` coercions: the
              // ring is the only thing a screen-reader user gets from this
              // chart, and it read "Generation $0.00" for a model with no
              // listed price - the measured-zero this whole change exists to
              // eliminate, surviving in the one place nobody looks.
              aria-label={`Generation ${
                llmSpend.kind === "priced"
                  ? formatCost(llmSpend.cost)
                  : SIDE_LABEL[llmSpend.kind][0].toLowerCase()
              }, embedding ${
                embedSpend.kind === "priced"
                  ? formatCost(embedSpend.cost)
                  : SIDE_LABEL[embedSpend.kind][0].toLowerCase()
              }`}
            >
              <div className="flex size-28 flex-col items-center justify-center rounded-full bg-card text-center shadow-[0_0_0_1px_var(--border)]">
                <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  {hasCompleteSpend ? 'Total spent' : 'Measured spend'}
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
              state={llmSpend}
            />
            <SpendLegendRow
              label="Embedding"
              description="Indexing and retrieval vectors"
              cost={embedding}
              percent={embeddingPct}
              color="var(--chart-2)"
              state={embedSpend}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-6 border-t border-border/70 pt-5">
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
        {/* Volume is measured from token counts and does not depend on any
            price, so it is reported whenever it exists. Only the spend-share
            clause needs both sides priced - gating the whole sentence on
            `hasCompleteSpend` told every Gemini/Cohere/local-embedder account
            that a fully measured comparison "is not measured", permanently,
            because only three embedders have a listed rate. */}
        {embeddingVolumePct != null ? (
          <span>
            Embedding produced {formatPercent(embeddingVolumePct)} of measured
            tokens
            {hasCompleteSpend ? (
              <>
                {" "}
                but only {formatPercent(embeddingPct)} of spend
                {costMultiple != null
                  ? `; generation cost ${costMultiple.toFixed(1)} times as much.`
                  : "."}
              </>
            ) : (
              "; its share of spend needs both sides to have a published rate."
            )}
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
  state,
}: {
  label: string
  description: string
  cost: number
  percent: number
  color: string
  /** Which of the four states this side is in. Replaces a pair of booleans
   * that could express "unmeasured" and "did not run" only by collapsing them
   * into each other - so a window where the provider reported no tokens
   * rendered as "nothing of this kind ran", directly under a tile counting
   * the tokens it did report. */
  state: SideSpend
}) {
  if (state.kind !== "priced") {
    const [headline, detail] = SIDE_LABEL[state.kind]
    return (
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className="mt-1 size-2.5 shrink-0 rounded-full opacity-40"
            style={{ background: color }}
          />
          <div>
            <div className="font-medium">{label}</div>
            <div className="text-xs text-muted-foreground">{description}</div>
          </div>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <div className="font-medium">{headline}</div>
          <div>{detail}</div>
        </div>
      </div>
    )
  }
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
      <CardContent className="flex flex-col gap-6">
        <div className="flex flex-col gap-4">
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
        <div className="grid grid-cols-2 gap-5 border-t border-border/70 pt-5 sm:grid-cols-3">
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
    <Alert className="usage-caveat border-border bg-card py-3.5">
      <Info />
      <AlertTitle>What these numbers leave out</AlertTitle>
      <AlertDescription>
        <p>
          Costs are your token counts priced at each provider&rsquo;s{" "}
          <em>public list rate</em>. Because the keys are yours, your real
          invoice can differ - free tiers, committed-use discounts, Azure
          deployment types and OpenRouter&rsquo;s markup all move the rate, and
          none of them is visible from the response.
        </p>
        {(caveats.unpriced_models ?? []).length > 0 && (
          <p>
            No published rate for {(caveats.unpriced_models ?? []).join(", ")},
            so their tokens are counted but their spend is not. For a model
            you run locally that is nothing; for a hosted one the cost figures
            above understate by whatever those calls cost you.
          </p>
        )}
        {caveats.vision_and_audio_excluded && (
          <p>
            Image captioning and audio transcription are not counted for this
            window: the provider returned no usage for them.
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
  // Keep chart identity stable across background refreshes.
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
    <div className="flex flex-col gap-3">
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
                key={`requests:${seriesKey}`}
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
                  isAnimationActive={false}
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
                  key={`tokens:${seriesKey}`}
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
                    isAnimationActive={false}
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
                    isAnimationActive={false}
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
                    isAnimationActive={false}
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
            Document ingestion - embedding, captioning and transcription - is
            metered here, so indexing spend appears as soon as a file is
            uploaded.
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
export function UsageDetails({ data }: { data: AccountUsage }) {
  if (data.totals.requests === 0) {
    return <EmptyState days={data.window_days} />
  }
  return (
    <div className="flex min-w-0 flex-col gap-6 sm:gap-8">
      <div>
        <TotalsRow
          totals={data.totals}
          days={data.window_days}
          caveats={data.caveats}
        />
      </div>
      <div>
        <div className="grid gap-4 lg:grid-cols-2">
          <SpendSplit totals={data.totals} caveats={data.caveats} />
          <CacheSavingsCard totals={data.totals} />
        </div>
      </div>
      <div>
        <CaveatsNote caveats={data.caveats} />
      </div>
      <div>
        <section className="flex flex-col gap-4" aria-labelledby="usage-activity-heading">
          <div className="usage-section-heading">
            <div>
              <h2 id="usage-activity-heading">Activity over time</h2>
              <p>Traffic, token volume and delivery performance across the selected window.</p>
            </div>
          </div>
          <DeferredUsagePanel label="Daily activity" layout="daily">
            <DailyTrends daily={data.daily} />
          </DeferredUsagePanel>
        </section>
      </div>
      <div>
        <section className="flex flex-col gap-4" aria-labelledby="usage-operations-heading">
          <div className="usage-section-heading">
            <div>
              <h2 id="usage-operations-heading">Operational performance</h2>
              <p>Latency, endpoint demand, cache behavior and retrieval quality.</p>
            </div>
          </div>
          {/* Operational half: how the system BEHAVED, next to what it spent. */}
          <DeferredUsagePanel label="Response time">
            <LatencyTrend daily={data.daily} />
          </DeferredUsagePanel>
          <div className="grid gap-4 lg:grid-cols-2 lg:[&>[data-usage-panel]]:grid">
            <DeferredUsagePanel label="Traffic by endpoint">
              <EndpointBreakdown rows={data.by_endpoint} />
            </DeferredUsagePanel>
            <DeferredUsagePanel label="Cache composition">
              <CacheTrend daily={data.daily} />
            </DeferredUsagePanel>
          </div>
          <DeferredUsagePanel label="Tokens by model">
            <ModelUsage rows={data.by_model} />
          </DeferredUsagePanel>
          <DeferredUsagePanel label="Retrieval quality">
            <RetrievalQuality daily={data.daily} />
          </DeferredUsagePanel>
        </section>
      </div>
      <div>
        <section className="flex flex-col gap-4" aria-labelledby="usage-allocation-heading">
          <div className="usage-section-heading">
            <div>
              <h2 id="usage-allocation-heading">Allocation &amp; governance</h2>
              <p>Trace account consumption across credentials, models and projects.</p>
            </div>
          </div>
          <DeferredUsagePanel label="Project portfolio">
            <ProjectPortfolio rows={data.by_project} />
          </DeferredUsagePanel>
          <DeferredUsagePanel label="API key usage">
            <ApiKeysTable rows={data.by_api_key} />
          </DeferredUsagePanel>
          <DeferredUsagePanel label="Model usage">
            <ModelsTable
              rows={data.by_model}
              unmeasuredModels={data.caveats.unmeasured_models}
            />
          </DeferredUsagePanel>
          <DeferredUsagePanel label="Project usage">
            <ProjectsTable rows={data.by_project} />
          </DeferredUsagePanel>
        </section>
      </div>
    </div>
  )
}
