/**
 * Small, theme-aware SVG illustrations for Best Practices tips - the same idea
 * as the Visualize tab's "Dimensions & this space" diagram, one per concept.
 *
 * All use currentColor via Tailwind text-* utilities: a muted base plus a sky
 * accent, so they read in both light and dark themes. Shared 120x40 canvas.
 */
import type { ReactNode } from "react"

const BOX = "h-9 w-full"

function Frame({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 120 40" className={BOX} role="img" aria-hidden="true">
      {children}
    </svg>
  )
}

/** A document split into overlapping chunks (chunk size / overlap). */
export function ChunkingViz() {
  return (
    <Frame>
      <rect x="6" y="6" width="34" height="28" rx="2" className="fill-none stroke-muted-foreground/50" strokeWidth="1.5" />
      {[0, 1, 2].map((i) => (
        <rect
          key={i}
          x={52 + i * 20}
          y={8 + (i % 2) * 4}
          width="24"
          height="18"
          rx="2"
          className={i === 1 ? "fill-sky-500/20 stroke-sky-500" : "fill-muted-foreground/10 stroke-muted-foreground/50"}
          strokeWidth="1.5"
        />
      ))}
      <path d="M44 20 L50 20" className="stroke-muted-foreground/60" strokeWidth="1.5" markerEnd="" />
    </Frame>
  )
}

/** Two cache layers (L1 exact + L2 semantic) served instantly. */
export function CacheViz() {
  return (
    <Frame>
      <rect x="10" y="7" width="46" height="11" rx="3" className="fill-sky-500/20 stroke-sky-500" strokeWidth="1.2" />
      <text x="14" y="15.5" className="fill-sky-600 dark:fill-sky-400" style={{ fontSize: 7, fontWeight: 600 }}>L1 exact</text>
      <rect x="10" y="22" width="46" height="11" rx="3" className="fill-muted-foreground/10 stroke-muted-foreground/50" strokeWidth="1.2" />
      <text x="14" y="30.5" className="fill-muted-foreground" style={{ fontSize: 7, fontWeight: 600 }}>L2 similar</text>
      <path d="M64 20 L82 20" className="stroke-muted-foreground/50" strokeWidth="1.5" />
      <path d="M100 12 L94 21 L99 21 L94 30" className="fill-none stroke-sky-500" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
    </Frame>
  )
}

/** Query fanning into vector + keyword search, fused (hybrid retrieval). */
export function RetrievalViz() {
  return (
    <Frame>
      <circle cx="12" cy="20" r="4" className="fill-sky-500" />
      <path d="M18 20 C30 20 30 11 42 11" className="fill-none stroke-muted-foreground/50" strokeWidth="1.2" />
      <path d="M18 20 C30 20 30 29 42 29" className="fill-none stroke-muted-foreground/50" strokeWidth="1.2" />
      {[0, 1, 2].map((i) => (
        <circle key={i} cx={48 + i * 7} cy="11" r="2.4" className="fill-sky-500/70" />
      ))}
      {[0, 1, 2].map((i) => (
        <rect key={i} x={45 + i * 8} y="27" width="6" height="4" rx="1" className="fill-muted-foreground/50" />
      ))}
      <path d="M74 11 C86 11 86 20 98 20" className="fill-none stroke-muted-foreground/50" strokeWidth="1.2" />
      <path d="M70 29 C86 29 86 20 98 20" className="fill-none stroke-muted-foreground/50" strokeWidth="1.2" />
      <rect x="100" y="14" width="14" height="12" rx="2" className="fill-sky-500/20 stroke-sky-500" strokeWidth="1.2" />
    </Frame>
  )
}

/** A key + dots (provider keys, shown-once, overrides). */
export function KeyViz() {
  return (
    <Frame>
      <circle cx="24" cy="20" r="9" className="fill-none stroke-sky-500" strokeWidth="2" />
      <circle cx="24" cy="20" r="3" className="fill-sky-500" />
      <path d="M33 20 L58 20 M50 20 L50 26 M58 20 L58 27" className="stroke-sky-500" strokeWidth="2" strokeLinecap="round" />
      {[0, 1, 2, 3].map((i) => (
        <circle key={i} cx={74 + i * 11} cy="20" r="2.6" className={i === 0 ? "fill-sky-500" : "fill-muted-foreground/40"} />
      ))}
    </Frame>
  )
}

/** Coins with a re-embed arrow (reindex / model-switch cost). */
export function CostViz() {
  return (
    <Frame>
      {[0, 1, 2].map((i) => (
        <ellipse key={i} cx="22" cy={30 - i * 6} rx="12" ry="4.5" className="fill-amber-500/20 stroke-amber-500/70" strokeWidth="1.2" />
      ))}
      <path d="M40 20 C56 12 66 12 80 20" className="fill-none stroke-muted-foreground/60" strokeWidth="1.5" />
      <path d="M76 15 L81 20 L75 23" className="fill-none stroke-muted-foreground/60" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      {[0, 1, 2].map((i) => (
        <circle key={i} cx={90 + i * 8} cy="20" r="3" className="fill-sky-500/70" />
      ))}
    </Frame>
  )
}

/** Clusters at high vs low dimensions (Matryoshka shrink). */
export function DimensionsViz() {
  const dots = (cx: number, spread: number, accent: boolean) =>
    [
      [cx - spread, 12],
      [cx + spread, 14],
      [cx, 26],
      [cx - spread * 0.6, 24],
      [cx + spread * 0.7, 24],
    ].map(([x, y], i) => (
      <circle key={i} cx={x} cy={y} r="2.4" className={accent && i === 0 ? "fill-sky-500" : "fill-muted-foreground/60"} />
    ))
  return (
    <Frame>
      <text x="8" y="9" className="fill-muted-foreground" style={{ fontSize: 6 }}>3072d</text>
      {dots(28, 12, true)}
      <line x1="60" y1="6" x2="60" y2="34" className="stroke-muted-foreground/25" strokeWidth="1" strokeDasharray="2 2" />
      <text x="80" y="9" className="fill-muted-foreground" style={{ fontSize: 6 }}>768d</text>
      {dots(94, 5, true)}
    </Frame>
  )
}

/** A note card with a pin (agent memory). */
export function MemoryViz() {
  return (
    <Frame>
      <rect x="12" y="8" width="34" height="24" rx="2" className="fill-muted-foreground/10 stroke-muted-foreground/50" strokeWidth="1.5" />
      <line x1="18" y1="15" x2="40" y2="15" className="stroke-muted-foreground/50" strokeWidth="1.5" />
      <line x1="18" y1="20" x2="36" y2="20" className="stroke-muted-foreground/40" strokeWidth="1.5" />
      <circle cx="42" cy="10" r="3.5" className="fill-sky-500" />
      <path d="M58 20 L74 20" className="stroke-muted-foreground/40" strokeWidth="1.2" strokeDasharray="2 2" />
      <circle cx="94" cy="20" r="9" className="fill-sky-500/15 stroke-sky-500/70" strokeWidth="1.2" />
      <path d="M90 20 q4 -6 8 0 q-4 6 -8 0" className="fill-sky-500/60" />
    </Frame>
  )
}

/** Chat bubbles with a follow-up (conversation memory). */
export function ConversationViz() {
  return (
    <Frame>
      <rect x="10" y="8" width="42" height="12" rx="4" className="fill-muted-foreground/15" />
      <rect x="30" y="22" width="42" height="12" rx="4" className="fill-sky-500/20 stroke-sky-500/60" strokeWidth="1" />
      <path d="M80 28 L96 28" className="stroke-muted-foreground/40" strokeWidth="1.2" />
      <path d="M92 24 L97 28 L92 32" className="fill-none stroke-muted-foreground/40" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="100" y="22" width="12" height="12" rx="3" className="fill-sky-500/20 stroke-sky-500/60" strokeWidth="1" />
    </Frame>
  )
}

/** Nodes and edges (the knowledge graph). */
export function GraphViz() {
  const nodes: [number, number, boolean][] = [
    [22, 12, false],
    [40, 26, true],
    [64, 10, false],
    [80, 28, false],
    [100, 16, true],
  ]
  const edges: [number, number][] = [
    [0, 1],
    [1, 2],
    [2, 4],
    [1, 3],
    [3, 4],
  ]
  return (
    <Frame>
      {edges.map(([a, b], i) => (
        <line key={i} x1={nodes[a][0]} y1={nodes[a][1]} x2={nodes[b][0]} y2={nodes[b][1]} className="stroke-muted-foreground/35" strokeWidth="1.2" />
      ))}
      {nodes.map(([x, y, accent], i) => (
        <circle key={i} cx={x} cy={y} r="4" className={accent ? "fill-sky-500" : "fill-muted-foreground/60"} />
      ))}
    </Frame>
  )
}

/** Bars representing top_k retrieved chunks (recall vs noise). */
export function TopKViz() {
  return (
    <Frame>
      {[0, 1, 2, 3, 4, 5, 6].map((i) => (
        <rect
          key={i}
          x={12 + i * 14}
          y={30 - (7 - i) * 3}
          width="8"
          height={(7 - i) * 3}
          rx="1.5"
          className={i < 3 ? "fill-sky-500" : "fill-muted-foreground/30"}
        />
      ))}
    </Frame>
  )
}

/** A file with a retry / refresh arrow (retry beats re-upload). */
export function RetryViz() {
  return (
    <Frame>
      <rect x="14" y="8" width="26" height="24" rx="2" className="fill-muted-foreground/10 stroke-muted-foreground/50" strokeWidth="1.5" />
      <path d="M52 20 a12 12 0 1 1 3 8" className="fill-none stroke-sky-500" strokeWidth="2" strokeLinecap="round" />
      <path d="M52 12 L52 20 L60 20" className="fill-none stroke-sky-500" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="86" y="8" width="26" height="24" rx="2" className="fill-sky-500/15 stroke-sky-500/60" strokeWidth="1.5" />
    </Frame>
  )
}
