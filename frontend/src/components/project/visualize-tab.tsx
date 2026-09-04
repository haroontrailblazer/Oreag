"use client"

import {
  ArrowsClockwiseIcon as ArrowsClockwise,
  ArrowsInIcon as ArrowsIn,
  ArrowsOutIcon as ArrowsOut,
  CornersOutIcon as CornersOut,
  FileTextIcon as FileText,
  HandIcon as Hand,
  MinusIcon as Minus,
  PlusIcon as Plus,
  XIcon as X,
} from "@phosphor-icons/react/dist/ssr"
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react"
import type ForceGraph3DComponent from "react-force-graph-3d"
import type {
  ForceGraphMethods,
  LinkObject,
  NodeObject,
} from "react-force-graph-3d"
import useSWR from "swr"
import {
  AdditiveBlending,
  DataTexture,
  LinearFilter,
  MOUSE,
  RGBAFormat,
  Sprite,
  SpriteMaterial,
  TOUCH,
  UnsignedByteType,
} from "three"

import { Badge } from "@/components/ui/badge"
import { BestPractices } from "@/components/ui/best-practices"
import {
  ClusterViz,
  EyeViz,
  GraphViz,
  PointerViz,
} from "@/components/ui/best-practice-visuals"
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
  MemoryGraphEdge,
  MemoryGraphNode,
  MemoryGraphResponse,
  Project,
} from "@/lib/types"
import { cn } from "@/lib/utils"

/* The canvas is pitch black in BOTH app themes - it is a viewing surface, not
   a page, and a single constant backdrop is what keeps the graph looking the
   same everywhere. So there is one palette rather than one per theme: the old
   light-theme colors (#475569 chunks, #3f3f46 edges) were picked to sit on
   near-white and would be close to invisible here.

   Files are the anchors, chunks the fine grain. The renderer multiplies edge
   colors by linkOpacity, so timid values disappear - keep them high-alpha. */
const CANVAS_BG = "#000000"
const NODE_COLORS: Record<string, string> = {
  project: "#f59e0b",
  file: "#38bdf8",
  section: "#a78bfa",
  chunk: "#64748b",
  memory: "#34d399",
  /* A dimmer shade of the memory green, not a new hue. A memory piece IS its
     parent, split - reading it as a separate kind of thing would undo the point
     of drawing it. Mirrors how a chunk sits beneath its file. */
  memory_chunk: "#059669",
}
const NODE_SIZES: Record<string, number> = {
  project: 10,
  file: 6,
  section: 3,
  chunk: 1.5,
  memory: 3,
  memory_chunk: 1.5,
}
/* Radius multiplier for every node, and the ONLY knob that scales them all
   uniformly. nodeVal above is a VOLUME - three-forcegraph derives the radius as
   cbrt(val) * nodeRelSize - so raising the values instead would need cubing to
   have any real effect, and would quietly distort the hierarchy on the way
   (cbrt already compresses a 6.7x range in val into a 1.9x range in radius).
   Multiplying here scales every node linearly and leaves those proportions
   exactly as tuned. Was the library default of 4; nodes read as too small. */
const NODE_REL_SIZE = 7
/* Sphere segments per node. The library default (8) is a visibly faceted
   lump at file/project size; 16 reads as round without meaningfully changing
   the triangle count at these radii. */
const NODE_RESOLUTION = 16
const LINK_COLORS: Record<string, string> = {
  related: "#38bdf8",
  contains: "rgba(212, 212, 216, 0.75)",
  next: "rgba(161, 161, 170, 0.55)",
  derived_from: "rgba(161, 161, 170, 0.4)",
}
/* Every non-zero width becomes real cylinder geometry in three-forcegraph.
   Relationship strength is expressed through diameter, while the higher
   radial resolution keeps the silhouette round instead of hexagonal. */
const LINK_WIDTHS: Record<string, number> = {
  related: 2.6,
  contains: 1.8,
  next: 1.2,
  derived_from: 1.1,
}
const LINK_RESOLUTION = 12

/* Straight links can visually pierce a third, unrelated node. Once the force
   layout settles, route only those colliding links around the occupied sphere.
   The padding includes the cylinder radius plus a small visible air gap. */
const LINK_NODE_GAP = 3
const LINK_ROUTE_DIRECTIONS = 16
const LINK_ROUTE_SAFETY = 1.08
const MAX_LINK_CURVATURE = 0.9

/* Node types are snake_case on the wire, and both the tooltip and the detail
   badge render them with CSS `capitalize` - which would print "Memory_chunk".
   One place to turn a type into words, so the two cannot drift apart. */
function typeLabel(type: string) {
  return type.replace(/_/g, " ")
}

const LEGEND = [
  { type: "file", label: "Files" },
  { type: "section", label: "Sections" },
  { type: "chunk", label: "Chunks" },
  { type: "memory", label: "Memories" },
  { type: "memory_chunk", label: "Memory pieces" },
] as const

/* A small camera-facing halo per node keeps the glow centred instead of letting
   directional sphere lighting bloom only one side of the graph. Anchor nodes
   carry the cluster glow; tiny chunks stay deliberately restrained so dense
   document groups remain sharp rather than merging into coloured fog. */
/* These sizes are ABSOLUTE world units, not multiples of the node, so they are
   coupled to NODE_REL_SIZE and must be scaled with it. At the previous values a
   chunk's halo (16) was ~1.7x its own diameter; after the node scale-up it
   would have been exactly 1.0x - the glow entirely inside the sphere, i.e.
   gone. Scaled by the same 1.75 so the tuned "very minimal glow" look survives
   the change instead of quietly disappearing. */
const NODE_GLOW: Record<string, { opacity: number; size: number }> = {
  project: { opacity: 0.4, size: 70 },
  file: { opacity: 0.32, size: 52 },
  section: { opacity: 0.24, size: 38 },
  chunk: { opacity: 0.1, size: 28 },
  memory: { opacity: 0.28, size: 38 },
  memory_chunk: { opacity: 0.1, size: 28 },
}

const GLOW_TEXTURE_SIZE = 64

/** Soft radial alpha with a clean edge. The colour is supplied by each
 * SpriteMaterial, so every node type can reuse the same tiny GPU texture. */
function createGlowTexture() {
  const data = new Uint8Array(GLOW_TEXTURE_SIZE * GLOW_TEXTURE_SIZE * 4)
  const center = (GLOW_TEXTURE_SIZE - 1) / 2

  for (let y = 0; y < GLOW_TEXTURE_SIZE; y += 1) {
    for (let x = 0; x < GLOW_TEXTURE_SIZE; x += 1) {
      const distance = Math.hypot(x - center, y - center) / center
      const falloff = Math.pow(Math.max(0, 1 - distance), 1.65)
      const offset = (y * GLOW_TEXTURE_SIZE + x) * 4
      data[offset] = 255
      data[offset + 1] = 255
      data[offset + 2] = 255
      data[offset + 3] = Math.round(falloff * 255)
    }
  }

  const texture = new DataTexture(
    data,
    GLOW_TEXTURE_SIZE,
    GLOW_TEXTURE_SIZE,
    RGBAFormat,
    UnsignedByteType
  )
  texture.minFilter = LinearFilter
  texture.magFilter = LinearFilter
  texture.generateMipmaps = false
  texture.needsUpdate = true
  return texture
}

const GLOW_TEXTURE = createGlowTexture()
const NODE_GLOW_MATERIALS = Object.fromEntries(
  Object.entries(NODE_GLOW).map(([type, style]) => [
    type,
    new SpriteMaterial({
      map: GLOW_TEXTURE,
      color: NODE_COLORS[type],
      opacity: style.opacity,
      transparent: true,
      blending: AdditiveBlending,
      depthTest: true,
      depthWrite: false,
      alphaTest: 0.01,
      toneMapped: false,
    }),
  ])
) as Record<string, SpriteMaterial>

/* Camera dolly per +/- press, and the distance band it may not leave: too
   close and the camera ends up inside the graph with nothing on screen, too
   far and the nodes collapse to a dot that no amount of clicking recovers. */
const ZOOM_STEP_IN = 0.78
const ZOOM_STEP_OUT = 1 / ZOOM_STEP_IN
const MIN_CAMERA_DISTANCE = 30
const MAX_CAMERA_DISTANCE = 6000

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)"

/** Subscribe to the OS "reduce motion" setting.
 *
 * useSyncExternalStore rather than an effect: matchMedia is external state, so
 * reading it in an effect body and calling setState is both a cascading render
 * and a frame of the wrong UI. The server snapshot is `false` because the
 * preference is unknowable there; the client corrects it during hydration.
 */
function usePrefersReducedMotion() {
  return useSyncExternalStore(
    (onChange) => {
      const query = window.matchMedia(REDUCED_MOTION_QUERY)
      query.addEventListener("change", onChange)
      return () => query.removeEventListener("change", onChange)
    },
    () => window.matchMedia(REDUCED_MOTION_QUERY).matches,
    () => false
  )
}

/** One control in the floating canvas toolbar. `active` marks a latched mode
 * (hand tool, auto-rotate) so the toolbar shows state, not just actions. */
function ToolButton({
  label,
  active,
  onClick,
  children,
}: {
  label: string
  active?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      title={label}
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "size-8 rounded-none text-muted-foreground hover:text-foreground",
        active && "bg-foreground/10 text-foreground"
      )}
    >
      {children}
    </Button>
  )
}

const BEST_PRACTICE_TIPS = [
  {
    visual: <ClusterViz />,
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
    visual: <PointerViz />,
    title: "Hover, then click",
    detail:
      "Hover shows a quick tooltip; clicking opens the details panel with a View file shortcut that jumps straight to the document.",
  },
  {
    visual: <EyeViz />,
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
type GLink = LinkObject<MemoryGraphNode, MemoryGraphEdge> & {
  __routeCurvature?: number
  __routeRotation?: number
}

type PositionedNode = GNode & { x: number; y: number; z: number }

const hasPosition = (node: GNode): node is PositionedNode =>
  Number.isFinite(node.x) && Number.isFinite(node.y) && Number.isFinite(node.z)

const nodeRadius = (node: GNode) =>
  Math.cbrt(Math.max(0, NODE_SIZES[node.type] ?? 2)) * NODE_REL_SIZE

/**
 * Bend links that intersect an unrelated node after the force simulation has
 * settled. Curvature is visual only: relationships and force layout stay
 * unchanged. A small spatial grid keeps this check local on large graphs.
 */
function routeLinksAroundNodes(nodes: GNode[], links: GLink[]) {
  const positionedNodes = nodes.filter(hasPosition)
  const byId = new Map(positionedNodes.map((node) => [String(node.id), node]))
  const maxNodeRadius = positionedNodes.reduce(
    (largest, node) => Math.max(largest, nodeRadius(node)),
    0
  )
  const maxLinkRadius = Math.max(...Object.values(LINK_WIDTHS)) / 2
  const maxClearance = maxNodeRadius + maxLinkRadius + LINK_NODE_GAP
  const cellSize = Math.max(1, maxClearance * 2)
  const grid = new Map<string, PositionedNode[]>()
  const cellKey = (x: number, y: number, z: number) =>
    `${Math.floor(x / cellSize)}:${Math.floor(y / cellSize)}:${Math.floor(z / cellSize)}`

  for (const node of positionedNodes) {
    const key = cellKey(node.x, node.y, node.z)
    const cell = grid.get(key)
    if (cell) cell.push(node)
    else grid.set(key, [node])
  }

  for (const link of links) {
    link.__routeCurvature = 0
    link.__routeRotation = 0

    const source =
      typeof link.source === "object"
        ? link.source
        : byId.get(String(link.source))
    const target =
      typeof link.target === "object"
        ? link.target
        : byId.get(String(link.target))
    if (!source || !target || !hasPosition(source) || !hasPosition(target)) {
      continue
    }

    const lx = target.x - source.x
    const ly = target.y - source.y
    const lz = target.z - source.z
    const lengthSquared = lx * lx + ly * ly + lz * lz
    if (lengthSquared < 1e-6) continue
    const length = Math.sqrt(lengthSquared)

    // Sample cells along the segment instead of comparing every link with
    // every node. Neighbouring cells cover the largest possible node sphere.
    const candidates = new Set<PositionedNode>()
    const sampleCount = Math.max(1, Math.ceil(length / (cellSize / 2)))
    for (let sample = 0; sample <= sampleCount; sample += 1) {
      const t = sample / sampleCount
      const x = source.x + lx * t
      const y = source.y + ly * t
      const z = source.z + lz * t
      const cx = Math.floor(x / cellSize)
      const cy = Math.floor(y / cellSize)
      const cz = Math.floor(z / cellSize)
      for (let dx = -1; dx <= 1; dx += 1) {
        for (let dy = -1; dy <= 1; dy += 1) {
          for (let dz = -1; dz <= 1; dz += 1) {
            for (const node of grid.get(`${cx + dx}:${cy + dy}:${cz + dz}`) ?? []) {
              candidates.add(node)
            }
          }
        }
      }
    }

    const linkRadius =
      (LINK_WIDTHS[(link as { type?: string }).type ?? ""] ?? 1.4) / 2
    const obstacles: {
      dx: number
      dy: number
      dz: number
      distanceSquared: number
      clearance: number
      t: number
    }[] = []

    for (const node of candidates) {
      if (node === source || node === target) continue
      const fromSourceX = node.x - source.x
      const fromSourceY = node.y - source.y
      const fromSourceZ = node.z - source.z
      const t =
        (fromSourceX * lx + fromSourceY * ly + fromSourceZ * lz) /
        lengthSquared
      if (t <= 0.02 || t >= 0.98) continue

      const closestX = source.x + lx * t
      const closestY = source.y + ly * t
      const closestZ = source.z + lz * t
      // From the obstacle towards the straight segment: bending in this
      // direction increases clearance instead of wrapping around the node.
      const dx = closestX - node.x
      const dy = closestY - node.y
      const dz = closestZ - node.z
      const distanceSquared = dx * dx + dy * dy + dz * dz
      const clearance = nodeRadius(node) + linkRadius + LINK_NODE_GAP
      if (distanceSquared < clearance * clearance) {
        obstacles.push({ dx, dy, dz, distanceSquared, clearance, t })
      }
    }

    if (!obstacles.length) continue

    const axisX = lx / length
    const axisY = ly / length
    const axisZ = lz / length
    // Matches three-forcegraph's zero-rotation reference direction.
    const referenceX = lx !== 0 || ly !== 0 ? ly : -lz
    const referenceY = lx !== 0 || ly !== 0 ? -lx : 0
    const referenceZ = lx !== 0 || ly !== 0 ? 0 : lx
    const referenceLength = Math.hypot(referenceX, referenceY, referenceZ)
    const baseX = referenceX / referenceLength
    const baseY = referenceY / referenceLength
    const baseZ = referenceZ / referenceLength
    const sideX = axisY * baseZ - axisZ * baseY
    const sideY = axisZ * baseX - axisX * baseZ
    const sideZ = axisX * baseY - axisY * baseX

    let bestControlOffset = Number.POSITIVE_INFINITY
    let bestRotation = 0

    // Choose the least-curved clear route around all nodes blocking this link,
    // rather than arbitrarily bending toward one obstacle and into another.
    for (let direction = 0; direction < LINK_ROUTE_DIRECTIONS; direction += 1) {
      const rotation = (direction / LINK_ROUTE_DIRECTIONS) * Math.PI * 2
      const ux = baseX * Math.cos(rotation) + sideX * Math.sin(rotation)
      const uy = baseY * Math.cos(rotation) + sideY * Math.sin(rotation)
      const uz = baseZ * Math.cos(rotation) + sideZ * Math.sin(rotation)
      let requiredControlOffset = 0

      for (const obstacle of obstacles) {
        const alongDirection =
          obstacle.dx * ux + obstacle.dy * uy + obstacle.dz * uz
        const discriminant =
          alongDirection * alongDirection +
          obstacle.clearance * obstacle.clearance -
          obstacle.distanceSquared
        const curveWeight = 2 * obstacle.t * (1 - obstacle.t)
        const needed =
          (-alongDirection + Math.sqrt(Math.max(0, discriminant))) /
          curveWeight
        requiredControlOffset = Math.max(requiredControlOffset, needed)
      }

      if (requiredControlOffset < bestControlOffset) {
        bestControlOffset = requiredControlOffset
        bestRotation = rotation
      }
    }

    link.__routeCurvature = Math.min(
      (bestControlOffset * LINK_ROUTE_SAFETY) / length,
      MAX_LINK_CURVATURE
    )
    link.__routeRotation = bestRotation
  }
}

function createNodeGlow(node: GNode) {
  const style = NODE_GLOW[node.type] ?? NODE_GLOW.section
  const material = NODE_GLOW_MATERIALS[node.type] ?? NODE_GLOW_MATERIALS.section

  const halo = new Sprite(material)
  halo.scale.setScalar(style.size)
  halo.renderOrder = 1
  // The halo is visual only. Leaving the Sprite raycast enabled would make
  // transparent pixels around the sphere behave like an oversized node hitbox.
  halo.raycast = () => undefined
  return halo
}

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
  // Auto-rotate follows the OS motion preference until the user overrides it
  // from the toolbar, so "reduce motion" gets a still canvas without taking
  // the control away.
  const reducedMotion = usePrefersReducedMotion()
  const [rotateOverride, setRotateOverride] = useState<boolean | null>(null)
  const rotating = rotateOverride ?? !reducedMotion
  // Hand tool: latched by the toolbar button, or held transiently with Space.
  const [panLatched, setPanLatched] = useState(false)
  const [spaceHeld, setSpaceHeld] = useState(false)
  const panning = panLatched || spaceHeld
  const [fullscreen, setFullscreen] = useState(false)
  // Set while navigating to the clicked file (Files tab load + scroll-to-row
  // takes a moment) - drives the "Locating file..." state on the button.
  const [locating, setLocating] = useState(false)

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

  // Everything that lives on the OrbitControls instance, in one place: rotate,
  // damping and which drag does what. Requires controlType="orbit" on the
  // graph - the default trackball controls have neither autoRotate nor a
  // mouseButtons map. Retries briefly because the graph (and its controls)
  // mount asynchronously after the module loads.
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
        enableDamping?: boolean
        dampingFactor?: number
        mouseButtons?: { LEFT: MOUSE; MIDDLE: MOUSE; RIGHT: MOUSE }
        touches?: { ONE: TOUCH; TWO: TOUCH }
      }
      controls.autoRotate = rotating
      controls.autoRotateSpeed = 0.9
      // Inertia. Safe to switch on because the renderer already calls
      // controls.update(delta) every frame (three-render-objects' tick), which
      // is what damping needs to keep easing after the pointer is released.
      controls.enableDamping = true
      controls.dampingFactor = 0.08
      // The hand tool. Right-drag pans in BOTH modes, so the muscle memory
      // that already worked keeps working; only left-drag changes meaning.
      controls.mouseButtons = {
        LEFT: panning ? MOUSE.PAN : MOUSE.ROTATE,
        MIDDLE: MOUSE.DOLLY,
        RIGHT: MOUSE.PAN,
      }
      controls.touches = {
        ONE: panning ? TOUCH.PAN : TOUCH.ROTATE,
        TWO: TOUCH.DOLLY_PAN,
      }
    }
    apply()
    return () => {
      cancelled = true
    }
  }, [rotating, panning, ForceGraph3D, graphData])

  // Space = temporary hand tool, the way every canvas app does it. Ignored
  // while typing, and cleared on blur: a Space held while the tab loses focus
  // never sees its keyup, which would otherwise strand the canvas in pan mode.
  useEffect(() => {
    const isTyping = (target: EventTarget | null) => {
      const el = target as HTMLElement | null
      return (
        !!el &&
        (el.tagName === "INPUT" ||
          el.tagName === "TEXTAREA" ||
          el.isContentEditable)
      )
    }
    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat || isTyping(e.target)) return
      e.preventDefault() // Space scrolls the page otherwise
      setSpaceHeld(true)
    }
    const up = (e: KeyboardEvent) => {
      if (e.code === "Space") setSpaceHeld(false)
    }
    const clear = () => setSpaceHeld(false)
    window.addEventListener("keydown", down)
    window.addEventListener("keyup", up)
    window.addEventListener("blur", clear)
    return () => {
      window.removeEventListener("keydown", down)
      window.removeEventListener("keyup", up)
      window.removeEventListener("blur", clear)
    }
  }, [])

  useEffect(() => {
    if (!graphData.nodes.length) return
    const timer = setTimeout(() => fgRef.current?.zoomToFit(600), 700)
    return () => clearTimeout(timer)
  }, [graphData, ForceGraph3D])

  // Full screen is an in-page overlay, not the Fullscreen API: the ask was a
  // panel floating over a blurred page, which the real API cannot do (it goes
  // edge to edge on a black backdrop). The graph element itself is only
  // re-styled, never re-parented, so the WebGL context, the camera and the
  // settled layout all survive the transition - the ResizeObserver above just
  // feeds the renderer its new box.
  useEffect(() => {
    if (!fullscreen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false)
    }
    window.addEventListener("keydown", onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      window.removeEventListener("keydown", onKey)
      document.body.style.overflow = previous
    }
  }, [fullscreen])

  /** Dolly the camera along its own view axis, toward whatever the orbit
   * target currently is - NOT toward the origin, which would drift the framing
   * sideways every press once the user has panned away from centre. */
  const dolly = useCallback((factor: number) => {
    const fg = fgRef.current
    if (!fg) return
    const controls = fg.controls() as {
      target?: { x: number; y: number; z: number }
    }
    const target = controls.target ?? { x: 0, y: 0, z: 0 }
    const camera = fg.camera()
    const next = {
      x: target.x + (camera.position.x - target.x) * factor,
      y: target.y + (camera.position.y - target.y) * factor,
      z: target.z + (camera.position.z - target.z) * factor,
    }
    const distance = Math.hypot(
      next.x - target.x,
      next.y - target.y,
      next.z - target.z
    )
    if (distance < MIN_CAMERA_DISTANCE || distance > MAX_CAMERA_DISTANCE) return
    fg.cameraPosition(next, target, 260)
  }, [])

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

  const fileIdOf = (node: MemoryGraphNode) => {
    if (node.type === "file") return node.id.slice("file:".length)
    const metadataFileId = node.metadata?.file_id
    return typeof metadataFileId === "string" ? metadataFileId : null
  }

  const selectedFileId = selected ? fileIdOf(selected) : null
  const selectedFileName = selected
    ? typeof selected.metadata?.filename === "string"
      ? selected.metadata.filename
      : data?.nodes.find(
          (node) =>
            node.type === "file" && node.id === `file:${selectedFileId}`
        )?.label ?? null
    : null

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <CardTitle>Knowledge graph</CardTitle>
            <CardDescription>
              Your project&apos;s brain in 3D - files, sections, chunks and
              agent memories, linked by meaning. Drag to rotate, scroll to
              zoom, click a node to inspect it.
            </CardDescription>
          </div>
          {/* View controls live on the canvas itself now (see the toolbar
              below), so the header keeps only what is not a canvas action. */}
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <BestPractices className="ml-auto" tips={BEST_PRACTICE_TIPS}>
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
                style={{ backgroundColor: NODE_COLORS[entry.type] }}
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

        {fullscreen && (
          // The blurred page behind the panel. Clicking it closes, which is
          // why it sits under the canvas rather than over it.
          <div
            className="fixed inset-0 z-40 bg-background/60 backdrop-blur-xl"
            onClick={() => setFullscreen(false)}
            aria-hidden
          />
        )}

        <div
          ref={boxRef}
          className={cn(
            // `dark` is load-bearing, not cosmetic: globals.css defines the
            // theme tokens under `.dark`, so scoping it here makes everything
            // inside the panel - loader, toolbar, details popup - render dark
            // whatever the app theme is. Without it a light-theme user gets a
            // white popup and a light loader floating on a black canvas.
            "dark relative overflow-hidden border border-zinc-800 bg-black",
            fullscreen
              ? // Half an inch of blurred page on every side, per the design.
                // Only the CSS changes here - the element is never re-parented,
                // so the WebGL context and the settled layout survive.
                "fixed inset-[0.5in] z-50 rounded-none shadow-2xl"
              : // Desktop: size the canvas to the space left under the page
                // header, tabs and card chrome (~22.5rem) so the whole tab fits
                // the viewport with no page scroll; phones keep a fixed height
                // and scroll as usual.
                "h-[52dvh] min-h-[320px] rounded-none sm:h-[420px] lg:h-[calc(100dvh-26rem)] lg:min-h-[380px]",
            // Only a hint - the canvas child sets its own cursor while dragging.
            panning && "cursor-grab active:cursor-grabbing"
          )}
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
              backgroundColor={CANVAS_BG}
              controlType="orbit"
              showNavInfo={false}
              // One tooltip treatment, because there is one canvas colour.
              nodeLabel={(node: GNode) =>
                `<div style="padding:6px 10px;border-radius:8px;background:rgba(24,24,27,.95);border:1px solid rgba(255,255,255,.12);color:#fafafa;font-size:12px;max-width:280px">
                   <div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(node.label)}</div>
                   <div style="color:#a1a1aa;text-transform:capitalize">${esc(typeLabel(node.type))}</div>
                 </div>`
              }
              nodeColor={(node: GNode) => NODE_COLORS[node.type] ?? "#e4e4e7"}
              nodeVal={(node: GNode) => NODE_SIZES[node.type] ?? 2}
              nodeRelSize={NODE_REL_SIZE}
              nodeResolution={NODE_RESOLUTION}
              nodeOpacity={0.98}
              nodeThreeObject={createNodeGlow}
              nodeThreeObjectExtend
              enableNodeDrag={false}
              linkColor={(link) =>
                LINK_COLORS[(link as { type?: string }).type ?? ""] ??
                "rgba(212, 212, 216, 0.6)"
              }
              linkOpacity={0.78}
              linkWidth={(link) =>
                LINK_WIDTHS[(link as { type?: string }).type ?? ""] ?? 1.4
              }
              linkResolution={LINK_RESOLUTION}
              linkCurvature={(link) =>
                (link as GLink).__routeCurvature ?? 0
              }
              linkCurveRotation={(link) =>
                (link as GLink).__routeRotation ?? 0
              }
              onEngineStop={() => {
                routeLinksAroundNodes(
                  graphData.nodes as GNode[],
                  graphData.links as GLink[]
                )
              }}
              onNodeClick={(node, event) => {
                event.stopPropagation()
                focusNode(node as GNode)
              }}
              onBackgroundClick={() => setSelected(null)}
            />
          )}

          {/* Canvas toolbar. Hidden while there is nothing to steer. */}
          {ForceGraph3D && data && !isEmpty && (
            <div className="absolute bottom-3 left-3 z-20 flex items-center gap-0.5 rounded-none border bg-background/80 p-1 shadow-lg backdrop-blur-md">
              <ToolButton label="Zoom out" onClick={() => dolly(ZOOM_STEP_OUT)}>
                <Minus className="size-4" />
              </ToolButton>
              <ToolButton label="Zoom in" onClick={() => dolly(ZOOM_STEP_IN)}>
                <Plus className="size-4" />
              </ToolButton>
              <ToolButton
                label="Fit graph to view"
                onClick={() => fgRef.current?.zoomToFit(600)}
              >
                <CornersOut className="size-4" />
              </ToolButton>
              <span className="mx-1 h-5 w-px bg-border" aria-hidden />
              <ToolButton
                label={
                  panLatched
                    ? "Hand tool on - drag to pan (or hold Space)"
                    : "Hand tool - drag to pan instead of rotate"
                }
                active={panning}
                onClick={() => setPanLatched((on) => !on)}
              >
                <Hand className="size-4" />
              </ToolButton>
              <ToolButton
                label={rotating ? "Stop rotation" : "Auto-rotate"}
                active={rotating}
                onClick={() => setRotateOverride(!rotating)}
              >
                <ArrowsClockwise className="size-4" />
              </ToolButton>
              <span className="mx-1 h-5 w-px bg-border" aria-hidden />
              <ToolButton
                label={fullscreen ? "Exit full screen (Esc)" : "Full screen"}
                onClick={() => setFullscreen((on) => !on)}
              >
                {fullscreen ? (
                  <ArrowsIn className="size-4" />
                ) : (
                  <ArrowsOut className="size-4" />
                )}
              </ToolButton>
            </div>
          )}

          {selected && (
            // Header (type + close) and the View-file action stay pinned; only
            // the middle body scrolls - with the custom scrollbar - so every
            // node popup (file, section, chunk, memory) behaves the same when
            // its text or metadata is long.
            <div
              className="absolute right-3 top-3 flex max-h-[calc(100%-1.5rem)] w-72 max-w-[calc(100%-1.5rem)] flex-col rounded-none border bg-background/95 p-4 text-foreground shadow-xl backdrop-blur"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => event.stopPropagation()}
            >
              <div className="flex shrink-0 items-start justify-between gap-2">
                <Badge variant="outline" className="capitalize">
                  <span
                    className="size-2 rounded-full"
                    style={{
                      backgroundColor: NODE_COLORS[selected.type] ?? "#71717a",
                    }}
                  />
                  {typeLabel(selected.type)}
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
                {selectedFileName && selected.type !== "file" && (
                  <p className="mb-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                    <FileText className="size-3.5 shrink-0" />
                    <span className="truncate" title={selectedFileName}>
                      {selectedFileName}
                    </span>
                  </p>
                )}
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
              {selectedFileId && (
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
                    onViewFile(selectedFileId)
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
