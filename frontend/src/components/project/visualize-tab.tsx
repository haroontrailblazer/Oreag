"use client"

import {
  ArrowsClockwise,
  CornersOut,
  FileText,
  X,
} from "@phosphor-icons/react/dist/ssr"
import { useTheme } from "next-themes"
import { useEffect, useMemo, useRef, useState } from "react"
import type ForceGraph3DComponent from "react-force-graph-3d"
import type { ForceGraphMethods, NodeObject } from "react-force-graph-3d"
import useSWR from "swr"

import { Badge } from "@/components/ui/badge"
import { BestPractices } from "@/components/ui/best-practices"
import { GraphViz } from "@/components/ui/best-practice-visuals"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { fetcher } from "@/lib/api"
import type {
  MemoryGraphNode,
  MemoryGraphResponse,
  Project,
} from "@/lib/types"

/* Colors / sizes per node kind - files are the anchors, chunks the fine grain.
   Separate palettes per theme so nodes and edges keep contrast on both
   canvases. The renderer multiplies edge colors by linkOpacity, so timid
   values disappear - keep them bright/high-alpha. */
const NODE_COLORS_DARK: Record<string, string> = {
  project: "#f59e0b",
  file: "#38bdf8",
  section: "#a78bfa",
  chunk: "#64748b",
  memory: "#34d399",
}
const NODE_COLORS_LIGHT: Record<string, string> = {
  project: "#d97706",
  file: "#0284c7",
  section: "#7c3aed",
  chunk: "#475569",
  memory: "#059669",
}
const NODE_SIZES: Record<string, number> = {
  project: 10,
  file: 6,
  section: 3,
  chunk: 1.5,
  memory: 3,
}
const LINK_COLORS_DARK: Record<string, string> = {
  related: "#38bdf8",
  contains: "rgba(212, 212, 216, 0.75)",
  next: "rgba(161, 161, 170, 0.55)",
  derived_from: "rgba(161, 161, 170, 0.4)",
}
const LINK_COLORS_LIGHT: Record<string, string> = {
  related: "#0284c7",
  contains: "rgba(63, 63, 70, 0.65)",
  next: "rgba(82, 82, 91, 0.5)",
  derived_from: "rgba(82, 82, 91, 0.38)",
}

const LEGEND = [
  { type: "file", label: "Files" },
  { type: "section", label: "Sections" },
  { type: "chunk", label: "Chunks" },
  { type: "memory", label: "Memories" },
] as const

const BEST_PRACTICE_TIPS = [
  {
    visual: <GraphViz />,
    title: "Read the clusters",
    detail:
      "Nodes that huddle together are semantically similar. A file whose chunks sit far from everything else may be off-topic for this project - or a unique source worth keeping.",
  },
  {
    visual: <GraphViz />,
    title: "Edges are relationships",
    detail:
      "Structural edges connect files to their chunks; similarity edges link related content across files and memories. Dense cross-file linking means your documents reinforce each other.",
  },
  {
    visual: <GraphViz />,
    title: "Hover, then click",
    detail:
      "Hover shows a quick tooltip; clicking opens the details panel with a View file shortcut that jumps straight to the document.",
  },
  {
    visual: <GraphViz />,
    title: "Watch it after big uploads",
    detail:
      "Re-open this view after indexing new files to sanity-check where they landed in the knowledge space.",
  },
]

/* Dot clusters for the dimensions illustration: the same three clusters drawn
   twice - well separated at 3072d, pulled together (outlines overlapping) at
   768d. One cluster takes the sky accent so the pairing reads at a glance. */
const DIM_CLUSTERS: {
  outline: [number, number, number]
  dots: [number, number][]
  accent?: boolean
}[][] = [
  [
    { outline: [34, 34, 13], dots: [[28, 30], [38, 28], [32, 40], [41, 37]], accent: true },
    { outline: [96, 30, 11], dots: [[91, 26], [101, 28], [95, 36]] },
    { outline: [62, 66, 12], dots: [[56, 63], [66, 61], [61, 71], [69, 69]] },
  ],
  [
    { outline: [198, 42, 13], dots: [[192, 38], [202, 36], [196, 48], [205, 45]], accent: true },
    { outline: [219, 37, 11], dots: [[214, 33], [224, 35], [218, 43]] },
    { outline: [209, 58, 12], dots: [[203, 55], [213, 53], [208, 63], [216, 61]] },
  ],
]

/** Theme-aware mini illustration: the same clusters at 3072 vs 768 dimensions -
 * fewer numbers, and the clusters pull closer until their borders overlap. */
function DimensionsIllustration() {
  return (
    <svg
      viewBox="0 0 280 96"
      className="w-full text-muted-foreground"
      aria-hidden="true"
    >
      <line
        x1="140"
        y1="8"
        x2="140"
        y2="78"
        strokeWidth="1"
        strokeDasharray="3 3"
        className="stroke-current opacity-25"
      />
      {DIM_CLUSTERS.map((panel, p) => (
        <g key={p}>
          {panel.map((cluster, c) => (
            <g key={c}>
              <circle
                cx={cluster.outline[0]}
                cy={cluster.outline[1]}
                r={cluster.outline[2]}
                fill="none"
                strokeWidth="1"
                strokeDasharray="3 3"
                className="stroke-current opacity-40"
              />
              {cluster.dots.map(([x, y]) => (
                <circle
                  key={`${x}-${y}`}
                  cx={x}
                  cy={y}
                  r="3"
                  className={
                    cluster.accent ? "fill-sky-500" : "fill-current opacity-70"
                  }
                />
              ))}
            </g>
          ))}
        </g>
      ))}
      <text
        x="66"
        y="92"
        textAnchor="middle"
        className="fill-current font-mono text-[9px]"
      >
        3072d
      </text>
      <text
        x="210"
        y="92"
        textAnchor="middle"
        className="fill-current font-mono text-[9px]"
      >
        768d
      </text>
    </svg>
  )
}

type GNode = NodeObject<MemoryGraphNode>

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")

/* Loader matching the Lottielab "Data | Ingesting" reference: a document card
   (grouped two-segment skeleton rows, one row flashing accent) streams a block
   of chunky aligned dashes into a tall 3-tier database cylinder whose rims
   light in sequence - recolored from orange to the app's sky accent. */
const CARD_ROWS: { y: number; segs: [number, number][]; accent?: boolean }[] = [
  { y: 30, segs: [[36, 48]] },
  { y: 40, segs: [[36, 58], [61, 72]] },
  { y: 47, segs: [[36, 62], [65, 74]], accent: true },
  { y: 54, segs: [[36, 54]] },
  { y: 66, segs: [[36, 60], [63, 72]] },
  { y: 73, segs: [[36, 56]] },
  { y: 80, segs: [[36, 64], [67, 74]] },
  { y: 92, segs: [[36, 46], [49, 54]] },
]
/* Top ellipse, middle seam and bottom rim of the cylinder, lit in turn. */
const DB_RIMS = [
  "M 163,44 A 22 8.5 0 1 0 207,44 A 22 8.5 0 1 0 163,44",
  "M 163,68 A 22 8.5 0 0 0 207,68",
  "M 163,92 A 22 8.5 0 0 0 207,92",
]
const CYCLE = "2.1s"

/** Tiny "searching the file" animation: a document with a scan line sweeping
 * down it. Inherits the button's text color. */
function FileScanIcon() {
  return (
    <svg viewBox="0 0 16 18" className="size-4" aria-hidden="true">
      <rect
        x="1.5"
        y="1.5"
        width="13"
        height="15"
        rx="2.5"
        fill="none"
        strokeWidth="1.5"
        className="stroke-current"
      />
      <line x1="4.5" y1="5" x2="11.5" y2="5" strokeWidth="1.5" strokeLinecap="round" className="stroke-current">
        <animate attributeName="y1" values="5;13;5" dur="1.1s" repeatCount="indefinite" />
        <animate attributeName="y2" values="5;13;5" dur="1.1s" repeatCount="indefinite" />
      </line>
    </svg>
  )
}

function GraphLoader() {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-8">
      <svg viewBox="0 0 240 116" className="w-72 max-w-[80%]" aria-hidden="true">
        {/* Source document - lifted fill + brighter strokes in dark mode so
            the composition reads on the near-black canvas. */}
        <rect
          x="28"
          y="20"
          width="64"
          height="86"
          rx="6"
          strokeWidth="1.5"
          className="fill-background stroke-border dark:fill-zinc-900 dark:stroke-zinc-600"
        />
        {CARD_ROWS.map((row, i) => (
          <g key={i}>
            {row.segs.map(([x1, x2], j) => (
              <g key={j}>
                <line
                  x1={x1}
                  y1={row.y}
                  x2={x2}
                  y2={row.y}
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  className="stroke-muted-foreground/25 dark:stroke-zinc-600/60"
                />
                {row.accent && (
                  // The row being ingested flashes accent, in step with the
                  // dash stream and the cylinder rims.
                  <line
                    x1={x1}
                    y1={row.y}
                    x2={x2}
                    y2={row.y}
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    className="stroke-zinc-700 dark:stroke-zinc-100"
                  >
                    <animate
                      attributeName="opacity"
                      values="0;1;1;0"
                      keyTimes="0;0.12;0.5;0.72"
                      dur={CYCLE}
                      repeatCount="indefinite"
                    />
                  </line>
                )}
              </g>
            ))}
          </g>
        ))}
        {/* Data stream: a fine block of thin aligned dashes on the move */}
        {[57, 60.4, 63.8, 67.2].map((y) => (
          <line
            key={y}
            x1="104"
            y1={y}
            x2="142"
            y2={y}
            strokeWidth="1.6"
            strokeLinecap="butt"
            strokeDasharray="4 2.5"
            className="stroke-zinc-700 dark:stroke-zinc-100"
          >
            <animate
              attributeName="stroke-dashoffset"
              values="0;-6.5"
              dur="0.8s"
              repeatCount="indefinite"
            />
          </line>
        ))}
        {/* Database cylinder */}
        <path
          d="M 163,44 L 163,92 A 22 8.5 0 0 0 207,92 L 207,44"
          fill="none"
          strokeWidth="1.5"
          className="stroke-border dark:stroke-zinc-600"
        />
        {DB_RIMS.map((d, i) => (
          <g key={i}>
            <path
              d={d}
              fill="none"
              strokeWidth="1.5"
              className="stroke-border dark:stroke-zinc-600"
            />
            {/* Accent sweep: each rim lights up in turn */}
            <path
              d={d}
              fill="none"
              strokeWidth="1.8"
              className="stroke-zinc-700 dark:stroke-zinc-100"
            >
              <animate
                attributeName="opacity"
                values="0;1;1;0"
                keyTimes="0;0.25;0.5;0.75"
                dur={CYCLE}
                begin={`${i * 0.7}s`}
                repeatCount="indefinite"
              />
            </path>
          </g>
        ))}
      </svg>
      <span className="rounded-full border bg-background px-4 py-1.5 font-mono text-xs text-zinc-700 dark:text-zinc-100">
        Visualizing...
      </span>
    </div>
  )
}

/** Interactive 3D view of the project's brain: files, sections, chunks and
 * agent memories as a force-directed graph. Drag to rotate, scroll to zoom,
 * right-drag to pan; hover for the label, click a node for its details. */
export function VisualizeTab({
  project,
  onViewFile,
}: {
  project: Project
  onViewFile: (fileId: string) => void
}) {
  const { data, isLoading } = useSWR<MemoryGraphResponse>(
    `/api/projects/${project.id}/memory-graph`,
    fetcher
  )

  // react-force-graph touches WebGL/window - load it on the client only. This
  // state-based import (vs next/dynamic) keeps the component's ref working.
  const [ForceGraph3D, setForceGraph3D] = useState<
    typeof ForceGraph3DComponent | null
  >(null)
  useEffect(() => {
    let alive = true
    import("react-force-graph-3d").then((mod) => {
      if (alive) setForceGraph3D(() => mod.default)
    })
    return () => {
      alive = false
    }
  }, [])

  const fgRef = useRef<ForceGraphMethods<MemoryGraphNode> | undefined>(undefined)
  const [selected, setSelected] = useState<MemoryGraphNode | null>(null)
  const [rotating, setRotating] = useState(true)
  // Set while navigating to the clicked file (Files tab load + scroll-to-row
  // takes a moment) - drives the "Locating file..." state on the button.
  const [locating, setLocating] = useState(false)

  // Theme-matched canvas: dark scene in dark mode, paper-light in light mode.
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme !== "light"
  const nodeColors = isDark ? NODE_COLORS_DARK : NODE_COLORS_LIGHT
  const linkColors = isDark ? LINK_COLORS_DARK : LINK_COLORS_LIGHT
  const canvasBg = isDark ? "#09090b" : "#fafafa"

  // The library mutates node/link objects (adds coordinates) - feed it clones.
  const graphData = useMemo(
    () => ({
      nodes: (data?.nodes ?? []).map((n) => ({ ...n })),
      links: (data?.edges ?? []).map((e) => ({ ...e })),
    }),
    [data]
  )

  // Measure the canvas box so the WebGL renderer gets exact pixel dimensions.
  const boxRef = useRef<HTMLDivElement | null>(null)
  const [size, setSize] = useState({ width: 0, height: 560 })
  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const observer = new ResizeObserver(() => {
      setSize({ width: el.clientWidth, height: el.clientHeight })
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ForceGraph3D])

  // Gentle auto-rotate until the user takes over; frame the graph on load.
  // Requires controlType="orbit" on the graph: the default trackball controls
  // have no autoRotate at all. Retries briefly because the graph (and its
  // controls) mount asynchronously after the module loads.
  useEffect(() => {
    let cancelled = false
    const apply = () => {
      if (cancelled) return
      const fg = fgRef.current
      if (!fg) {
        setTimeout(apply, 200)
        return
      }
      const controls = fg.controls() as {
        autoRotate?: boolean
        autoRotateSpeed?: number
      }
      controls.autoRotate = rotating
      controls.autoRotateSpeed = 0.9
    }
    apply()
    return () => {
      cancelled = true
    }
  }, [rotating, ForceGraph3D, graphData])

  useEffect(() => {
    if (!graphData.nodes.length) return
    const timer = setTimeout(() => fgRef.current?.zoomToFit(600), 700)
    return () => clearTimeout(timer)
  }, [graphData, ForceGraph3D])

  function focusNode(node: GNode) {
    setSelected({
      id: node.id,
      type: node.type,
      label: node.label,
      text: node.text,
      metadata: node.metadata,
    })
    const { x, y, z } = node
    if (x == null || y == null || z == null) return
    const distance = 90
    const ratio = 1 + distance / (Math.hypot(x, y, z) || 1)
    fgRef.current?.cameraPosition(
      { x: x * ratio, y: y * ratio, z: z * ratio },
      { x, y, z },
      900
    )
  }

  // A brain with just the project node has nothing to show yet.
  const isEmpty = !isLoading && data && data.nodes.length <= 1

  const fileIdOf = (node: MemoryGraphNode) =>
    node.type === "file" ? node.id.slice("file:".length) : null

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Knowledge graph</CardTitle>
            <CardDescription>
              Your project&apos;s brain in 3D - files, sections, chunks and
              agent memories, linked by meaning. Drag to rotate, scroll to
              zoom, click a node to inspect it.
            </CardDescription>
          </div>
          {/* Compact icon buttons on phones; labels appear from sm: up. */}
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-label={rotating ? "Stop rotation" : "Auto-rotate"}
              onClick={() => setRotating((r) => !r)}
            >
              <ArrowsClockwise className="size-4" />
              <span className="hidden sm:inline">
                {rotating ? "Stop rotation" : "Auto-rotate"}
              </span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-label="Reset view"
              onClick={() => fgRef.current?.zoomToFit(600)}
            >
              <CornersOut className="size-4" />
              <span className="hidden sm:inline">Reset view</span>
            </Button>
            <BestPractices tips={BEST_PRACTICE_TIPS}>
              <div className="space-y-1.5 border-t pt-3">
                <p className="text-xs font-medium">Dimensions & this space</p>
                <DimensionsIllustration />
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Embedding dimensions set how finely this space separates
                  meanings. More dimensions keep near-duplicate topics
                  distinguishable; shrinking (Matryoshka) packs the same
                  meaning into fewer numbers - clusters pull closer and
                  borderline matches blur first. Shrinking the same model is
                  instant in Settings -&gt; Indexing &amp; embedding; growing
                  back needs a full re-index.
                </p>
              </div>
            </BestPractices>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {LEGEND.map((entry) => (
            <span key={entry.type} className="inline-flex items-center gap-1.5">
              <span
                className="size-2.5 rounded-full"
                style={{ backgroundColor: nodeColors[entry.type] }}
              />
              {entry.label}
            </span>
          ))}
          {data && (
            <span className="ml-auto font-mono">
              {data.nodes.length} nodes · {data.edges.length} edges
            </span>
          )}
        </div>

        <div
          ref={boxRef}
          // Desktop: size the canvas to the space left under the page header,
          // tabs and card chrome (~22.5rem) so the whole tab fits the viewport
          // with no page scroll; phones keep a fixed height and scroll as usual.
          className="relative h-[52dvh] min-h-[320px] overflow-hidden rounded-xl border bg-zinc-50 sm:h-[420px] lg:h-[calc(100dvh-26rem)] lg:min-h-[380px] dark:border-zinc-800 dark:bg-[#09090b]"
        >
          {(isLoading || !ForceGraph3D) && <GraphLoader />}

          {isEmpty && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center">
              <p className="text-sm text-foreground">Nothing to visualize yet</p>
              <p className="max-w-sm text-xs text-muted-foreground">
                Upload and index documents (or save agent memories) and the
                brain graph will grow here.
              </p>
            </div>
          )}

          {ForceGraph3D && data && !isEmpty && size.width > 0 && (
            <ForceGraph3D
              ref={fgRef}
              width={size.width}
              height={size.height}
              graphData={graphData}
              backgroundColor={canvasBg}
              controlType="orbit"
              showNavInfo={false}
              nodeLabel={(node: GNode) =>
                isDark
                  ? `<div style="padding:6px 10px;border-radius:8px;background:rgba(24,24,27,.95);border:1px solid rgba(255,255,255,.12);color:#fafafa;font-size:12px;max-width:280px">
                       <div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(node.label)}</div>
                       <div style="color:#a1a1aa;text-transform:capitalize">${esc(node.type)}</div>
                     </div>`
                  : `<div style="padding:6px 10px;border-radius:8px;background:rgba(255,255,255,.97);border:1px solid rgba(0,0,0,.12);color:#18181b;font-size:12px;max-width:280px;box-shadow:0 4px 12px rgba(0,0,0,.08)">
                       <div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(node.label)}</div>
                       <div style="color:#52525b;text-transform:capitalize">${esc(node.type)}</div>
                     </div>`
              }
              nodeColor={(node: GNode) =>
                nodeColors[node.type] ?? (isDark ? "#e4e4e7" : "#3f3f46")
              }
              nodeVal={(node: GNode) => NODE_SIZES[node.type] ?? 2}
              nodeOpacity={0.92}
              linkColor={(link) =>
                linkColors[(link as { type?: string }).type ?? ""] ??
                (isDark ? "rgba(212, 212, 216, 0.6)" : "rgba(63, 63, 70, 0.5)")
              }
              linkOpacity={0.9}
              linkWidth={(link) =>
                (link as { type?: string }).type === "related" ? 1.8 : 0.7
              }
              onNodeClick={(node) => focusNode(node as GNode)}
              onBackgroundClick={() => setSelected(null)}
            />
          )}

          {selected && (
            // Header (type + close) and the View-file action stay pinned; only
            // the middle body scrolls - with the custom scrollbar - so every
            // node popup (file, section, chunk, memory) behaves the same when
            // its text or metadata is long.
            <div className="absolute right-3 top-3 flex max-h-[calc(100%-1.5rem)] w-72 max-w-[calc(100%-1.5rem)] flex-col rounded-xl border bg-background/95 p-4 text-foreground shadow-xl backdrop-blur">
              <div className="flex shrink-0 items-start justify-between gap-2">
                <Badge variant="outline" className="capitalize">
                  <span
                    className="size-2 rounded-full"
                    style={{
                      backgroundColor: nodeColors[selected.type] ?? "#71717a",
                    }}
                  />
                  {selected.type}
                </Badge>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Close details"
                  className="size-6 text-muted-foreground hover:text-foreground"
                  onClick={() => setSelected(null)}
                >
                  <X className="size-3.5" />
                </Button>
              </div>
              <div className="styled-scrollbar mt-2 min-h-0 flex-1 overflow-y-auto pr-1">
                <p className="break-words text-sm font-medium leading-snug">
                  {selected.label}
                </p>
                {selected.text && (
                  <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed text-muted-foreground">
                    {selected.text}
                  </p>
                )}
                <dl className="mt-3 space-y-1 text-[11px] text-muted-foreground">
                  {Object.entries(selected.metadata ?? {})
                    .filter(([, v]) => v != null && v !== "" && String(v) !== "[]")
                    .slice(0, 5)
                    .map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-3">
                        <dt className="shrink-0 capitalize">
                          {k.replaceAll("_", " ")}
                        </dt>
                        <dd className="truncate font-mono text-foreground/80">
                          {Array.isArray(v) ? v.join(", ") : String(v)}
                        </dd>
                      </div>
                    ))}
                </dl>
              </div>
              {fileIdOf(selected) && (
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-3 w-full shrink-0"
                  disabled={locating}
                  onClick={() => {
                    // Switch tabs via the page's client state - NOT
                    // router.push: pushing an unchanged ?file= URL is a no-op
                    // the second time and stranded this button on
                    // "Locating file...".
                    setLocating(true)
                    onViewFile(fileIdOf(selected) as string)
                  }}
                >
                  {locating ? (
                    <>
                      <FileScanIcon />
                      <span className="font-mono text-xs">Locating file...</span>
                    </>
                  ) : (
                    <>
                      <FileText className="size-4" />
                      View file
                    </>
                  )}
                </Button>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
