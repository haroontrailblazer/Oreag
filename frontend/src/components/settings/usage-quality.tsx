"use client"

/**
 * Quality and model-mix charts for the Usage page.
 *
 * Separate from usage-monitoring.tsx because these answer a different question:
 * that file is "is it fast and what is it doing", this one is "is it any good
 * and where is the volume going".
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "recharts"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"
import type { UsageByModel, UsageDaily } from "@/lib/types"

const intFmt = new Intl.NumberFormat("en-US")
const compact = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
})

function dayLabel(date: string): string {
  const [y, m, d] = date.split("-").map(Number)
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  })
}

const axisProps = {
  tickLine: false,
  axisLine: false,
  tickMargin: 8,
  className: "text-[11px]",
} as const

/* ── retrieval quality ─────────────────────────────────────────────────── */

export function RetrievalQuality({ daily }: { daily: UsageDaily[] }) {
  const series = [...daily].sort((a, b) => (a.date < b.date ? -1 : 1))
  const measured = series.filter((d) => d.avg_retrieval_similarity != null)

  // One or two points is not a trend. Say the number instead of drawing a line
  // through it - similarity has only been recorded since the usage-analytics
  // migration, so a young account genuinely has nothing to plot yet.
  if (measured.length < 3) {
    const latest = measured.at(-1)?.avg_retrieval_similarity
    return (
      <Card className="gap-3">
        <CardHeader>
          <CardTitle className="text-base">Retrieval quality</CardTitle>
          <CardDescription>
            Mean similarity of the chunks retrieval returned. Needs a few days
            of queries before there is a trend worth drawing.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="pb-2 text-sm text-muted-foreground">
            {latest == null
              ? "Not measured yet."
              : `Only ${measured.length} day${measured.length === 1 ? "" : "s"} measured so far — currently ${latest.toFixed(2)}.`}
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="text-base">Retrieval quality</CardTitle>
        <CardDescription>
          Mean similarity of the chunks retrieval returned each day. A sustained
          fall means the index is drifting away from what people ask — the one
          quality signal here that costs nothing to collect.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {/* Single series: no legend box, the title names it. */}
        <ChartContainer
          config={{
            avg_retrieval_similarity: {
              label: "Avg similarity",
              color: "var(--chart-3)",
            },
          }}
          className="h-52 w-full"
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
              tickFormatter={(v) => dayLabel(String(v))}
              {...axisProps}
            />
            {/* Fixed 0..1 domain: similarity is a bounded score, and an
                auto-fitted axis would turn a 0.02 wobble into a cliff. */}
            <YAxis
              width={40}
              domain={[0, 1]}
              tickFormatter={(v) => Number(v).toFixed(1)}
              {...axisProps}
            />
            <ChartTooltip
              content={
                <ChartTooltipContent
                  labelFormatter={(v) => dayLabel(String(v))}
                  formatter={(value) => [
                    ` ${Number(value).toFixed(3)}`,
                    "Avg similarity",
                  ]}
                />
              }
            />
            <Line
              dataKey="avg_retrieval_similarity"
              type="monotone"
              stroke="var(--color-avg_retrieval_similarity)"
              strokeWidth={2}
              dot={{
                r: 3,
                fill: "var(--color-avg_retrieval_similarity)",
                stroke: "var(--card)",
                strokeWidth: 2,
              }}
              activeDot={{ r: 4 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}

/* ── tokens by model ───────────────────────────────────────────────────── */

function ModelBars({
  rows,
  color,
  label,
}: {
  rows: UsageByModel[]
  color: string
  label: string
}) {
  const data = rows.map((r) => ({
    model: r.model,
    tokens: (r.prompt_tokens ?? 0) + (r.completion_tokens ?? 0),
    requests: r.requests,
    cost: r.cost_usd,
  }))

  return (
    <div className="min-w-0 flex-1">
      <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      {data.length === 0 ? (
        <p className="text-sm text-muted-foreground">None in this window.</p>
      ) : (
        <ChartContainer
          config={{ tokens: { label: "Tokens", color } }}
          style={{ height: `${Math.max(90, data.length * 36)}px` }}
          className="w-full"
        >
          <BarChart
            accessibilityLayer
            data={data}
            layout="vertical"
            margin={{ top: 4, right: 56, left: 4, bottom: 4 }}
          >
            <CartesianGrid horizontal={false} />
            <XAxis type="number" hide />
            <YAxis type="category" dataKey="model" width={140} {...axisProps} />
            <ChartTooltip
              content={
                <ChartTooltipContent
                  formatter={(value, _name, item) => {
                    const row = item?.payload as {
                      requests: number
                      cost: number | null
                    }
                    const cost =
                      row?.cost != null ? ` · $${row.cost.toFixed(4)}` : ""
                    return [
                      ` ${intFmt.format(Number(value))} tokens`,
                      `· ${row?.requests} req${cost}`,
                    ]
                  }}
                />
              }
            />
            <Bar
              dataKey="tokens"
              fill="var(--color-tokens)"
              radius={[0, 4, 4, 0]}
              // Direct labels: a single series needs no legend, and the
              // light-mode contrast warning on this palette obliges visible
              // values rather than colour alone.
              label={{
                position: "right",
                className: "fill-muted-foreground text-[11px] tabular-nums",
                formatter: (v: unknown) => compact.format(Number(v ?? 0)),
              }}
              isAnimationActive={false}
            />
          </BarChart>
        </ChartContainer>
      )}
    </div>
  )
}

export function ModelUsage({ rows }: { rows: UsageByModel[] }) {
  // TWO charts, not one with two series, and never a second y-axis.
  //
  // Embedding volume runs orders of magnitude above generation - measured on
  // this account, 222,610 embedding tokens against 1,640 chat tokens. On one
  // shared linear axis every generation model collapses to an invisible
  // sliver. Small multiples, each scaled to its own kind, is the honest form.
  const llm = rows.filter((r) => r.kind === "llm")
  const embedding = rows.filter((r) => r.kind === "embedding")

  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="text-base">Tokens by model</CardTitle>
        <CardDescription>
          Two charts on purpose: embedding volume runs orders of magnitude above
          generation, so a shared axis would flatten every chat model to
          nothing. Each side is scaled to its own kind.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6 sm:flex-row sm:gap-8">
        <ModelBars rows={llm} color="var(--chart-1)" label="Generation" />
        <ModelBars rows={embedding} color="var(--chart-3)" label="Embedding" />
      </CardContent>
    </Card>
  )
}
