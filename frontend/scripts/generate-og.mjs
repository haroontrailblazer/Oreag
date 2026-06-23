// One-off: render the brand OG card to a static PNG at public/og.png using the
// same engine (next/og) as the route version. Run: `node scripts/generate-og.mjs`
//
// Design: the real Oreag logo inside the 3D "app-icon" badge (matching the
// .brand-mark treatment in globals.css), an Oreag wordmark, the amber/sky accent
// tagline from the landing hero, and feature pills — on a dark canvas with a soft
// brand-coloured glow.
import { readFileSync, writeFileSync } from "node:fs"
import { createRequire } from "node:module"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

import React from "react"

const here = dirname(fileURLToPath(import.meta.url))
// next/og's "./og" subpath isn't in the package exports map, so import the
// compiled ImageResponse by absolute path (bypasses the exports restriction).
const require = createRequire(import.meta.url)
const { ImageResponse } = require(
  join(here, "..", "node_modules", "next", "dist", "server", "og", "image-response.js")
)

const h = React.createElement

// The dark badge needs a light mark (same as the dashboard's dark-mode
// `dark:invert`). satori can't apply CSS filters, so recolour the vector logo's
// fills to white directly and embed the SVG.
let logoSvg = readFileSync(join(here, "..", "public", "logo.svg"), "utf8")
logoSvg = logoSvg.replace(/fill="#[0-9a-fA-F]+"/g, 'fill="#ffffff"')
const logoSrc = `data:image/svg+xml;base64,${Buffer.from(logoSvg).toString("base64")}`

// The 3D badge — same gradient + layered shadows as `.brand-mark` (light), with a
// child gloss overlay standing in for the CSS ::after (satori has no pseudos).
const badge = h(
  "div",
  {
    style: {
      position: "relative",
      width: "300px",
      height: "300px",
      borderRadius: "64px",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      overflow: "hidden",
      border: "1px solid rgba(255,255,255,0.06)",
      background: "linear-gradient(160deg, #2b2e32 0%, #161719 55%, #0a0b0c 100%)",
      boxShadow:
        "inset 0 2px 0 0 rgba(255,255,255,0.16), inset 0 -6px 14px -4px rgba(0,0,0,0.55), 0 2px 4px 0 rgba(0,0,0,0.5), 0 36px 70px -20px rgba(0,0,0,0.8)",
    },
  },
  h("img", {
    src: logoSrc,
    width: 232,
    height: 232,
    style: { objectFit: "contain" },
  }),
  h("div", {
    style: {
      position: "absolute",
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background:
        "linear-gradient(180deg, rgba(255,255,255,0.12) 0%, rgba(255,255,255,0) 45%)",
    },
  })
)

// Accent tagline (amber "documents", sky "RAG API") — built as coloured word
// chips so satori lays them out inline without inline-text quirks.
const phrase = [
  ["Turn your", "#a1a1aa"],
  ["documents", "#f59e0b"],
  ["into a queryable", "#a1a1aa"],
  ["RAG API", "#38bdf8"],
]
const tagline = h(
  "div",
  {
    style: {
      display: "flex",
      flexWrap: "wrap",
      maxWidth: "600px",
      fontSize: "34px",
      fontWeight: 600,
      lineHeight: 1.25,
    },
  },
  phrase.map(([word, color], i) =>
    h("div", { key: i, style: { display: "flex", color, marginRight: "11px" } }, word)
  )
)

const pills = h(
  "div",
  { style: { display: "flex", gap: "14px", marginTop: "8px" } },
  ["BYOK", "pgvector", "Memory Graph"].map((t, i) =>
    h(
      "div",
      {
        key: i,
        style: {
          display: "flex",
          padding: "11px 24px",
          borderRadius: "9999px",
          border: "1px solid #3f3f46",
          color: "#e4e4e7",
          fontSize: "26px",
        },
      },
      t
    )
  )
)

const rightColumn = h(
  "div",
  { style: { display: "flex", flexDirection: "column", gap: "22px" } },
  h(
    "div",
    {
      style: {
        display: "flex",
        fontSize: "94px",
        fontWeight: 800,
        color: "#ffffff",
        letterSpacing: "-4px",
        lineHeight: 1,
      },
    },
    "Oreag"
  ),
  tagline,
  pills
)

const element = h(
  "div",
  {
    style: {
      width: "100%",
      height: "100%",
      display: "flex",
      position: "relative",
      fontFamily: "sans-serif",
      background: "linear-gradient(135deg, #1c1c21 0%, #0a0a0a 100%)",
    },
  },
  h("div", {
    style: {
      position: "absolute",
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background:
        "radial-gradient(circle at 84% 16%, rgba(56,189,248,0.18) 0%, rgba(0,0,0,0) 42%)",
    },
  }),
  h("div", {
    style: {
      position: "absolute",
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background:
        "radial-gradient(circle at 12% 92%, rgba(245,158,11,0.12) 0%, rgba(0,0,0,0) 40%)",
    },
  }),
  h(
    "div",
    {
      style: {
        position: "relative",
        display: "flex",
        width: "100%",
        height: "100%",
        alignItems: "center",
        justifyContent: "center",
        gap: "68px",
        padding: "72px",
      },
    },
    badge,
    rightColumn
  )
)

const res = new ImageResponse(element, { width: 1200, height: 630 })
const buf = Buffer.from(await res.arrayBuffer())
const out = join(here, "..", "public", "og.png")
writeFileSync(out, buf)
console.log("WROTE", out, buf.length, "bytes")
