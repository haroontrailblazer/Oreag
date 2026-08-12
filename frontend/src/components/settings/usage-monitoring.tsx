"use client"

/**
 * Monitoring charts for the Usage page - the operational half, alongside the
 * spend half already on the page.
 *
 * WHY THESE THREE AND NOT MORE
 *
 * Each one answers a question the account previously could not ask at all, and
 * each is backed by data that is actually recorded:
 *
 *   1. Latency percentiles  - "is it getting slower, and for whom"
 *   2. Traffic by endpoint  - "what is this account actually doing"
 *   3. Cache composition    - "is the cache earning its keep, over time"
 *
 * Deliberately ABSENT, because the data does not exist rather than because the
 * chart would be uninteresting: error rate (no request outcome is recorded on
 * usage_events), time-to-first-token, and tokens/second. Drawing any of those
 * would mean inventing the series.
 *
 * Retrieval similarity is collected but only since migration 0027, so most
 * accounts have a couple of days of it. It rides in the daily table rather
 * than getting a chart of its own until there is a trend to see - two points
 * is not a line.
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
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"
import type { UsageByEndpoint, UsageDaily } from "@/lib/types"

const intFmt = new Intl.NumberFormat("en-US")

/** Milliseconds, rendered at the scale a human reads them at. */
function ms(value: number): string {
  if (value < 1000) return `${Math.round(value)}ms`
  return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)}s`
}

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

/* ── 1. latency percentiles ────────────────────────────────────────────── */

// Categorical, in fixed order - p50/p95/p99 are three distinct series, not a
// magnitude ramp. Never cycled: a fourth percentile would replace one of these
// rather than generate a hue.
const latencyConfig = {
  p50_latency_ms: { label: "p50 (typical)", color: "var(--chart-1)" },
  p95_latency_ms: { label: "p95 (slow tail)", color: "var(--chart-4)" },
  p99_latency_ms: { label: "p99 (worst)", color: "var(--chart-2)" },
} satisfies ChartConfig

export function LatencyTrend({ daily }: { daily: UsageDaily[] }) {
  const series = [...daily].sort((a, b) => (a.date < b.date ? -1 : 1))
  const measured = series.some((d) => d.p50_latency_ms != null)

  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="text-base">Response time</CardTitle>
        <CardDescription>
          Percentiles, not an average - a mean latency hides exactly the slow
          tail it is asked about. p95 is the request users complain about.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!measured ? (
          <p className="pb-2 text-sm text-muted-foreground">
            No timed queries in this window.
          </p>
        ) : (
          <ChartContainer config={latencyConfig} className="h-56 w-full">
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
              <YAxis
                width={48}
                tickFormatter={(v) => ms(Number(v))}
                {...axisProps}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    labelFormatter={(v) => dayLabel(String(v))}
                    formatter={(value, name) => [
                      ` ${ms(Number(value))}`,
                      latencyConfig[name as keyof typeof latencyConfig]?.label ??
                        name,
                    ]}
                  />
                }
              />
              <ChartLegend content={<ChartLegendContent />} />
              {(
                ["p50_latency_ms", "p95_latency_ms", "p99_latency_ms"] as const
              ).map((key) => (
                <Line
                  key={key}
                  dataKey={key}
                  type="monotone"
                  stroke={`var(--color-${key})`}
                  strokeWidth={2}
                  dot={
                    series.length <= 14
                      ? {
                          r: 3,
                          fill: `var(--color-${key})`,
                          stroke: "var(--card)",
                          strokeWidth: 2,
                        }
                      : false
                  }
                  activeDot={{ r: 4 }}
                  // A day with no timed query is a GAP, not a zero-latency day.
                  connectNulls={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}

/* ── 2. traffic by endpoint ────────────────────────────────────────────── */

export function EndpointBreakdown({ rows }: { rows: UsageByEndpoint[] }) {
  // Horizontal bars: the labels are long identifiers, and a horizontal axis
  // would either truncate or rotate them. Top 8 - past that the bars are
  // unreadable and the tail is noise; the count is stated rather than silently
  // truncated.
  const top = rows.slice(0, 8)
  const hidden = rows.length - top.length

  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="text-base">Traffic by endpoint</CardTitle>
        <CardDescription>
          Which surfaces this account actually uses. Recorded since metering
          began and never shown until now, so a spike in spend could not be
          attributed to anything.
          {hidden > 0 && ` ${hidden} smaller endpoint${hidden === 1 ? "" : "s"} not shown.`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {top.length === 0 ? (
          <p className="pb-2 text-sm text-muted-foreground">
            No requests in this window.
          </p>
        ) : (
          <ChartContainer
            config={{ requests: { label: "Requests", color: "var(--chart-1)" } }}
            style={{ height: `${Math.max(140, top.length * 34)}px` }}
            className="w-full"
          >
            <BarChart
              accessibilityLayer
              data={top}
              layout="vertical"
              margin={{ top: 4, right: 44, left: 4, bottom: 4 }}
            >
              <CartesianGrid horizontal={false} />
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="endpoint"
                width={150}
                {...axisProps}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    formatter={(value, _name, item) => {
                      const row = item?.payload as UsageByEndpoint
                      const latency = row?.p50_latency_ms
                      return [
                        ` ${intFmt.format(Number(value))} requests`,
                        latency != null ? `· ${ms(latency)} typical` : "",
                      ]
                    }}
                  />
                }
              />
              <Bar
                dataKey="requests"
                fill="var(--color-requests)"
                // Rounded data-end, square against the baseline.
                radius={[0, 4, 4, 0]}
                // Direct labels: a single series needs no legend, and the
                // contrast WARN on this palette obliges visible values.
                label={{
                  position: "right",
                  className: "fill-muted-foreground text-[11px] tabular-nums",
                  formatter: (v: unknown) => intFmt.format(Number(v ?? 0)),
                }}
                isAnimationActive={false}
              />
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}

/* ── 3. cache composition over time ────────────────────────────────────── */

const cacheConfig = {
  cache_l1: { label: "L1 exact", color: "var(--chart-3)" },
  cache_l2: { label: "L2 semantic", color: "var(--chart-1)" },
  cache_miss: { label: "Miss", color: "var(--muted-foreground)" },
} satisfies ChartConfig

export function CacheTrend({ daily }: { daily: UsageDaily[] }) {
  const series = [...daily].sort((a, b) => (a.date < b.date ? -1 : 1))
  const answered = series.some(
    (d) => d.cache_l1 + d.cache_l2 + d.cache_miss > 0
  )
  const hits = series.reduce((n, d) => n + d.cache_l1 + d.cache_l2, 0)
  const total = series.reduce(
    (n, d) => n + d.cache_l1 + d.cache_l2 + d.cache_miss,
    0
  )

  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="text-base">Cache composition</CardTitle>
        <CardDescription>
          Every answered query, split by what served it.{" "}
          {total > 0 && (
            <>
              {((hits / total) * 100).toFixed(0)}% came from cache over this
              window - those skipped the model entirely.
            </>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!answered ? (
          <p className="pb-2 text-sm text-muted-foreground">
            No queries in this window.
          </p>
        ) : (
          <ChartContainer config={cacheConfig} className="h-56 w-full">
            <BarChart
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
              <YAxis width={36} allowDecimals={false} {...axisProps} />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    labelFormatter={(v) => dayLabel(String(v))}
                  />
                }
              />
              <ChartLegend content={<ChartLegendContent />} />
              {(["cache_l1", "cache_l2", "cache_miss"] as const).map((key) => (
                <Bar
                  key={key}
                  dataKey={key}
                  stackId="cache"
                  fill={`var(--color-${key})`}
                  // 2px of surface between stacked segments, so adjacent fills
                  // read as separate marks rather than one blended block.
                  stroke="var(--card)"
                  strokeWidth={2}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}
