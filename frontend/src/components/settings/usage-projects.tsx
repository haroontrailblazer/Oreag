"use client"

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"

import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
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
import type { UsageByProject } from "@/lib/types"

const MAX_CHART_PROJECTS = 6

const intFmt = new Intl.NumberFormat("en-US")
const currencyFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const axisProps = {
  tickLine: false,
  axisLine: false,
  tickMargin: 8,
  className: "text-[11px]",
} as const

const qualityConfig = {
  hit_rate: { label: "Cache hit rate", color: "var(--chart-1)" },
  retrieval_quality: {
    label: "Retrieval similarity",
    color: "var(--chart-3)",
  },
  cache_similarity: {
    label: "Cache similarity",
    color: "var(--chart-4)",
  },
} satisfies ChartConfig

function shortProjectName(name: string): string {
  return name.length > 20 ? `${name.slice(0, 18)}…` : name
}

function percentage(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function ProjectPortfolio({ rows }: { rows: UsageByProject[] }) {
  const projects = [...rows]
    .sort((a, b) => b.requests - a.requests)
    .slice(0, MAX_CHART_PROJECTS)
    .map((row) => ({
      ...row,
      project: shortProjectName(row.name),
      retrieval_quality: row.avg_retrieval_similarity,
      cache_similarity: row.avg_cache_similarity,
      hit_rate: row.cache.hit_rate,
    }))

  const hiddenProjects = Math.max(0, rows.length - projects.length)
  const measuredSpend = rows.filter((row) => row.cost_usd != null)
  const totalMeasuredSpend = measuredSpend.reduce(
    (sum, row) => sum + (row.cost_usd ?? 0),
    0
  )
  const highestSpend = [...measuredSpend].sort(
    (a, b) => (b.cost_usd ?? 0) - (a.cost_usd ?? 0)
  )[0]
  const strongestCache = [...rows].sort(
    (a, b) => b.cache.hit_rate - a.cache.hit_rate
  )[0]
  const highestSpendShare =
    highestSpend?.cost_usd != null && totalMeasuredSpend > 0
      ? highestSpend.cost_usd / totalMeasuredSpend
      : null

  return (
    <Card className="usage-chart-card usage-project-portfolio gap-0 overflow-hidden">
      <CardHeader className="border-b border-border/70 pb-5">
        <CardTitle className="text-base">Project portfolio</CardTitle>
        <CardDescription>
          Compare spend, request demand, cache efficiency and retrieval quality
          across projects.
          {hiddenProjects > 0 &&
            ` Showing the ${projects.length} highest-volume projects; ${hiddenProjects} more ${hiddenProjects === 1 ? "is" : "are"} available in the table below.`}
        </CardDescription>
      </CardHeader>

      {projects.length === 0 ? (
        <CardContent className="py-6 text-sm text-muted-foreground">
          No project usage in this window.
        </CardContent>
      ) : (
        <CardContent className="grid p-0 lg:grid-cols-2">
          <section className="min-w-0 border-b border-border/70 p-6 lg:border-r lg:border-b-0">
            <div className="mb-4">
              <h3 className="text-sm font-semibold tracking-[-0.015em]">
                Spend by project
              </h3>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                Measured provider cost. Hover for demand and cost per request.
              </p>
            </div>
            <ChartContainer
              config={{
                cost_usd: { label: "Spend", color: "var(--chart-1)" },
              }}
              style={{ height: `${Math.max(210, projects.length * 44)}px` }}
              className="w-full"
            >
              <BarChart
                accessibilityLayer
                data={projects}
                layout="vertical"
                margin={{ top: 4, right: 54, left: 0, bottom: 4 }}
              >
                <CartesianGrid horizontal={false} />
                <XAxis type="number" hide />
                <YAxis
                  type="category"
                  dataKey="project"
                  width={128}
                  {...axisProps}
                />
                <ChartTooltip
                  content={
                    <ChartTooltipContent
                      hideLabel
                      formatter={(value, _name, item) => {
                        const row = item?.payload as (typeof projects)[number]
                        const costPerRequest =
                          row.cost_usd != null && row.requests > 0
                            ? row.cost_usd / row.requests
                            : null
                        return [
                          row.cost_usd == null
                            ? " Cost not measured"
                            : ` ${currencyFmt.format(Number(value))} · ${intFmt.format(row.requests)} requests${costPerRequest == null ? "" : ` · ${currencyFmt.format(costPerRequest)}/request`}`,
                          row.name,
                        ]
                      }}
                    />
                  }
                />
                <Bar
                  dataKey="cost_usd"
                  fill="var(--color-cost_usd)"
                  radius={[0, 4, 4, 0]}
                  label={{
                    position: "right",
                    className:
                      "fill-muted-foreground text-[11px] tabular-nums",
                    formatter: (value: unknown) =>
                      value == null ? "" : currencyFmt.format(Number(value)),
                  }}
                  isAnimationActive={false}
                />
              </BarChart>
            </ChartContainer>
          </section>

          <section className="min-w-0 p-6">
            <div className="mb-4">
              <h3 className="text-sm font-semibold tracking-[-0.015em]">
                Quality &amp; cache efficiency
              </h3>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                Comparable 0–100% signals. Missing provider measurements remain
                gaps, not zeroes.
              </p>
            </div>
            <ChartContainer
              config={qualityConfig}
              style={{ height: `${Math.max(230, projects.length * 48)}px` }}
              className="w-full"
            >
              <BarChart
                accessibilityLayer
                data={projects}
                layout="vertical"
                margin={{ top: 4, right: 10, left: 0, bottom: 4 }}
              >
                <CartesianGrid horizontal={false} />
                <XAxis
                  type="number"
                  domain={[0, 1]}
                  ticks={[0, 0.5, 1]}
                  tickFormatter={(value) => percentage(Number(value))}
                  {...axisProps}
                />
                <YAxis
                  type="category"
                  dataKey="project"
                  width={128}
                  {...axisProps}
                />
                <ChartTooltip
                  content={
                    <ChartTooltipContent
                      formatter={(value, name, item) => {
                        const row = item?.payload as (typeof projects)[number]
                        return [
                          ` ${percentage(Number(value))}`,
                          `${qualityConfig[name as keyof typeof qualityConfig]?.label ?? name} · ${row.name}`,
                        ]
                      }}
                    />
                  }
                />
                <ChartLegend content={<ChartLegendContent />} />
                {(Object.keys(qualityConfig) as (keyof typeof qualityConfig)[]).map(
                  (key) => (
                    <Bar
                      key={key}
                      dataKey={key}
                      fill={`var(--color-${key})`}
                      radius={[0, 3, 3, 0]}
                      barSize={8}
                      isAnimationActive={false}
                    />
                  )
                )}
              </BarChart>
            </ChartContainer>
          </section>
        </CardContent>
      )}

      {projects.length > 0 && (highestSpend || strongestCache) && (
        <CardFooter className="flex flex-wrap gap-x-2 gap-y-1 border-t bg-muted/20 py-4 text-xs leading-relaxed text-muted-foreground">
          {highestSpend && highestSpendShare != null && (
            <span>
              <strong className="font-medium text-foreground">
                {highestSpend.name}
              </strong>{" "}
              represents {percentage(highestSpendShare)} of measured project
              spend.
            </span>
          )}
          {highestSpend && highestSpendShare != null && strongestCache && (
            <span aria-hidden="true">·</span>
          )}
          {strongestCache && (
            <span>
              <strong className="font-medium text-foreground">
                {strongestCache.name}
              </strong>{" "}
              leads cache efficiency at {percentage(strongestCache.cache.hit_rate)}.
            </span>
          )}
        </CardFooter>
      )}
    </Card>
  )
}
