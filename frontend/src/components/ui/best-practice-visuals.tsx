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

/* ---------------------------------------------------------------------------
 * Extra distinct visuals so no Best Practices list ever repeats an icon - one
 * per concept, same 120x40 canvas, muted base + sky accent.
 * ------------------------------------------------------------------------- */

/** A tight cluster of similar points beside a lone outlier (read the clusters). */
export function ClusterViz() {
  return (
    <Frame>
      <circle cx="42" cy="20" r="13" className="fill-none stroke-muted-foreground/25" strokeWidth="1" strokeDasharray="3 3" />
      {[[36, 15], [48, 17], [40, 25], [50, 23], [43, 20]].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="2.4" className="fill-sky-500" />
      ))}
      <line x1="70" y1="10" x2="70" y2="30" className="stroke-muted-foreground/25" strokeWidth="1" strokeDasharray="2 2" />
      <circle cx="96" cy="20" r="2.8" className="fill-muted-foreground/60" />
    </Frame>
  )
}

/** Nodes with a cursor aimed at the highlighted one (hover, then click). */
export function PointerViz() {
  return (
    <Frame>
      <circle cx="28" cy="14" r="4" className="fill-muted-foreground/50" />
      <circle cx="48" cy="27" r="4" className="fill-muted-foreground/50" />
      <circle cx="64" cy="14" r="5" className="fill-sky-500" />
      <path d="M70 18 L70 34 L74.5 29.5 L77.5 35.5 L80 34.5 L77 28.5 L83 28.5 Z" className="fill-sky-600 dark:fill-sky-400" strokeLinejoin="round" />
    </Frame>
  )
}

/** An eye watching a spread of points (re-check the space after uploads). */
export function EyeViz() {
  return (
    <Frame>
      <path d="M34 20 Q52 8 70 20 Q52 32 34 20 Z" className="fill-sky-500/15 stroke-sky-500" strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx="52" cy="20" r="3.6" className="fill-sky-500" />
      {[[88, 13], [98, 20], [88, 27]].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="2.2" className="fill-muted-foreground/50" />
      ))}
    </Frame>
  )
}

/** A server (safe) versus a crossed-out browser (never ship keys client-side). */
export function ServerViz() {
  return (
    <Frame>
      {[0, 1, 2].map((i) => (
        <rect key={i} x="14" y={8 + i * 8} width="30" height="6" rx="1.5" className="fill-sky-500/20 stroke-sky-500" strokeWidth="1.2" />
      ))}
      <circle cx="19" cy="11" r="1" className="fill-sky-500" />
      <circle cx="19" cy="19" r="1" className="fill-sky-500" />
      <path d="M50 20 L62 20 M58 16 L62 20 L58 24" className="fill-none stroke-muted-foreground/60" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="72" y="10" width="34" height="22" rx="2" className="fill-none stroke-muted-foreground/50" strokeWidth="1.5" />
      <line x1="72" y1="16" x2="106" y2="16" className="stroke-muted-foreground/50" strokeWidth="1.2" />
      <path d="M77 13 L101 29 M101 13 L77 29" className="stroke-red-500/70" strokeWidth="1.5" strokeLinecap="round" />
    </Frame>
  )
}

/** Three separate keys (one key per consumer). */
export function KeysMultiViz() {
  const key = (x: number, accent: boolean) => (
    <g key={x}>
      <circle cx={x} cy="20" r="5" className={accent ? "fill-none stroke-sky-500" : "fill-none stroke-muted-foreground/50"} strokeWidth="1.8" />
      <circle cx={x} cy="20" r="1.6" className={accent ? "fill-sky-500" : "fill-muted-foreground/50"} />
      <path d={`M${x + 5} 20 L${x + 16} 20 M${x + 11} 20 L${x + 11} 24 M${x + 16} 20 L${x + 16} 25`} className={accent ? "stroke-sky-500" : "stroke-muted-foreground/50"} strokeWidth="1.8" strokeLinecap="round" />
    </g>
  )
  return (
    <Frame>
      {key(16, true)}
      {key(52, false)}
      {key(88, false)}
    </Frame>
  )
}

/** A project key stacked on top of an account key (project overrides account). */
export function OverrideViz() {
  return (
    <Frame>
      <rect x="34" y="21" width="60" height="13" rx="3" className="fill-muted-foreground/10 stroke-muted-foreground/40" strokeWidth="1.2" />
      <text x="42" y="30" className="fill-muted-foreground" style={{ fontSize: 6 }}>account</text>
      <rect x="20" y="7" width="60" height="13" rx="3" className="fill-sky-500/20 stroke-sky-500" strokeWidth="1.3" />
      <text x="28" y="16" className="fill-sky-600 dark:fill-sky-400" style={{ fontSize: 6, fontWeight: 600 }}>project</text>
    </Frame>
  )
}

/** A document beside supported-format badges (file types / size limit). */
export function DocTypesViz() {
  return (
    <Frame>
      <path d="M40 7 h18 l8 8 v18 h-26 Z" className="fill-muted-foreground/10 stroke-muted-foreground/50" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M58 7 v8 h8" className="fill-none stroke-muted-foreground/50" strokeWidth="1.5" />
      <line x1="43" y1="22" x2="61" y2="22" className="stroke-muted-foreground/40" strokeWidth="1.5" />
      <line x1="43" y1="27" x2="57" y2="27" className="stroke-muted-foreground/40" strokeWidth="1.5" />
      <rect x="78" y="12" width="22" height="8" rx="2" className="fill-sky-500/20 stroke-sky-500" strokeWidth="1" />
      <text x="81" y="18.4" className="fill-sky-600 dark:fill-sky-400" style={{ fontSize: 5.5, fontWeight: 600 }}>PDF</text>
      <rect x="78" y="22" width="22" height="8" rx="2" className="fill-muted-foreground/10 stroke-muted-foreground/50" strokeWidth="1" />
      <text x="80.5" y="28.4" className="fill-muted-foreground" style={{ fontSize: 5.5, fontWeight: 600 }}>DOCX</text>
    </Frame>
  )
}

/** A file with adjustment sliders (per-file chunking overrides). */
export function SlidersViz() {
  return (
    <Frame>
      <rect x="18" y="8" width="26" height="24" rx="2" className="fill-muted-foreground/10 stroke-muted-foreground/50" strokeWidth="1.5" />
      <line x1="56" y1="15" x2="102" y2="15" className="stroke-muted-foreground/40" strokeWidth="1.5" />
      <circle cx="74" cy="15" r="3.6" className="fill-sky-500" />
      <line x1="56" y1="25" x2="102" y2="25" className="stroke-muted-foreground/40" strokeWidth="1.5" />
      <circle cx="88" cy="25" r="3.6" className="fill-sky-500" />
    </Frame>
  )
}

/** A row of reference/citation chips (click the source chips). */
export function ChipsViz() {
  const chip = (x: number, accent: boolean) => (
    <g key={x}>
      <rect x={x} y="14" width="30" height="12" rx="6" className={accent ? "fill-sky-500/20 stroke-sky-500" : "fill-muted-foreground/10 stroke-muted-foreground/50"} strokeWidth="1.1" />
      <circle cx={x + 7} cy="20" r="2" className={accent ? "fill-sky-500" : "fill-muted-foreground/50"} />
      <line x1={x + 12} y1="20" x2={x + 25} y2="20" className={accent ? "stroke-sky-500/70" : "stroke-muted-foreground/40"} strokeWidth="1.4" />
    </g>
  )
  return (
    <Frame>
      {chip(8, true)}
      {chip(45, false)}
      {chip(82, false)}
    </Frame>
  )
}

/** Connected stages passing a request through (same /v1 pipeline). */
export function PipelineViz() {
  return (
    <Frame>
      {[10, 50, 90].map((x, i) => (
        <rect key={i} x={x} y="13" width="20" height="14" rx="2" className={i === 1 ? "fill-sky-500/20 stroke-sky-500" : "fill-muted-foreground/10 stroke-muted-foreground/50"} strokeWidth="1.2" />
      ))}
      <path d="M30 20 L50 20 M46 16 L50 20 L46 24" className="fill-none stroke-muted-foreground/60" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M70 20 L90 20 M86 16 L90 20 L86 24" className="fill-none stroke-muted-foreground/60" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </Frame>
  )
}

/** Tags feeding a filter funnel (tag for humans, not for search). */
export function TagViz() {
  const tag = (y: number, accent: boolean) => (
    <g key={y}>
      <path d={`M20 ${y} L36 ${y} L44 ${y + 6} L36 ${y + 12} L20 ${y + 12} Z`} className={accent ? "fill-sky-500/20 stroke-sky-500" : "fill-muted-foreground/10 stroke-muted-foreground/50"} strokeWidth="1.2" strokeLinejoin="round" />
      <circle cx="25" cy={y + 6} r="1.6" className={accent ? "fill-sky-500" : "fill-muted-foreground/50"} />
    </g>
  )
  return (
    <Frame>
      {tag(8, true)}
      {tag(22, false)}
      <path d="M76 12 L104 12 L94 22 L94 30 L86 26 L86 22 Z" className="fill-muted-foreground/10 stroke-muted-foreground/50" strokeWidth="1.3" strokeLinejoin="round" />
    </Frame>
  )
}

/** A note held down by a pushpin (pin what must persist). */
export function PinViz() {
  return (
    <Frame>
      <rect x="28" y="11" width="40" height="23" rx="2" className="fill-muted-foreground/10 stroke-muted-foreground/50" strokeWidth="1.5" />
      <line x1="34" y1="19" x2="58" y2="19" className="stroke-muted-foreground/40" strokeWidth="1.5" />
      <line x1="34" y1="25" x2="52" y2="25" className="stroke-muted-foreground/40" strokeWidth="1.5" />
      <path d="M66 8 L66 16" className="stroke-sky-500" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="66" cy="8" r="4.5" className="fill-sky-500" />
      <circle cx="66" cy="8" r="1.6" className="fill-sky-200 dark:fill-sky-900" />
    </Frame>
  )
}

/** A note pointing at empty (dashed) vector slots (unembedded = invisible). */
export function VectorViz() {
  return (
    <Frame>
      <rect x="12" y="10" width="26" height="20" rx="2" className="fill-muted-foreground/10 stroke-muted-foreground/50" strokeWidth="1.5" />
      <line x1="17" y1="17" x2="33" y2="17" className="stroke-muted-foreground/40" strokeWidth="1.4" />
      <line x1="17" y1="22" x2="29" y2="22" className="stroke-muted-foreground/40" strokeWidth="1.4" />
      <path d="M42 20 L54 20 M50 16.5 L54 20 L50 23.5" className="fill-none stroke-muted-foreground/50" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" strokeDasharray="2 2" />
      {[0, 1, 2, 3].map((i) => (
        <circle key={i} cx={64 + i * 12} cy="20" r="3" className="fill-none stroke-muted-foreground/40" strokeWidth="1.2" strokeDasharray="2 1.5" />
      ))}
    </Frame>
  )
}
