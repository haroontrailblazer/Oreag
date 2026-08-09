// Render the brand OG card to public/og.png. Run:
// `node scripts/generate-og.mjs`
//
// The composition mirrors the landing page: its painterly document-work scene
// stays full bleed, while the real app icon and exact product copy remain crisp
// code-native layers for reliable social-preview rendering.
import { readFileSync, writeFileSync } from "node:fs"
import { createRequire } from "node:module"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

import React from "react"

const here = dirname(fileURLToPath(import.meta.url))
const publicDir = join(here, "..", "public")
const require = createRequire(import.meta.url)
const { ImageResponse } = require(
  join(
    here,
    "..",
    "node_modules",
    "next",
    "dist",
    "server",
    "og",
    "image-response.js"
  )
)

const h = React.createElement

function imageDataUrl(filename, mimeType) {
  const bytes = readFileSync(join(publicDir, filename))
  return `data:${mimeType};base64,${bytes.toString("base64")}`
}

const paintingSrc = imageDataUrl("og-painting.png", "image/png")
const iconSrc = imageDataUrl("../src/app/icon.png", "image/png")

const brand = h(
  "div",
  {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "20px",
    },
  },
  h("img", {
    src: iconSrc,
    width: 88,
    height: 88,
    style: {
      borderRadius: "22px",
      boxShadow: "0 18px 40px rgba(0,0,0,0.42)",
    },
  }),
  h(
    "div",
    { style: { display: "flex", flexDirection: "column", gap: "5px" } },
    h(
      "div",
      {
        style: {
          display: "flex",
          color: "#ffffff",
          fontSize: "58px",
          fontWeight: 760,
          letterSpacing: "-2.5px",
          lineHeight: 1,
        },
      },
      "Oreag"
    ),
    h(
      "div",
      {
        style: {
          display: "flex",
          color: "rgba(255,255,255,0.74)",
          fontSize: "22px",
          fontWeight: 500,
          letterSpacing: "0.2px",
        },
      },
      "RAG & Memory as a Service"
    )
  )
)

const headline = h(
  "div",
  {
    style: {
      display: "flex",
      flexDirection: "column",
      width: "650px",
      color: "#ffffff",
      fontSize: "50px",
      fontWeight: 680,
      lineHeight: 1.08,
      letterSpacing: "-1.8px",
    },
  },
  h("div", { style: { display: "flex" } }, "Turn your documents into"),
  h(
    "div",
    { style: { display: "flex", alignItems: "baseline", gap: "14px" } },
    h("div", { style: { display: "flex" } }, "a queryable"),
    h(
      "div",
      {
        style: {
          display: "flex",
          color: "#7dd3fc",
          textShadow: "0 3px 18px rgba(14,165,233,0.28)",
        },
      },
      "RAG API"
    )
  )
)

const element = h(
  "div",
  {
    style: {
      width: "100%",
      height: "100%",
      display: "flex",
      position: "relative",
      overflow: "hidden",
      fontFamily: "sans-serif",
      background: "#06142f",
    },
  },
  h("img", {
    src: paintingSrc,
    width: 1200,
    height: 630,
    style: {
      position: "absolute",
      inset: 0,
      width: "100%",
      height: "100%",
      objectFit: "cover",
      objectPosition: "center",
    },
  }),
  h("div", {
    style: {
      position: "absolute",
      inset: 0,
      background:
        "linear-gradient(90deg, rgba(2,8,23,0.88) 0%, rgba(2,8,23,0.66) 42%, rgba(2,8,23,0.08) 72%, rgba(2,8,23,0) 100%)",
    },
  }),
  h("div", {
    style: {
      position: "absolute",
      inset: 0,
      background:
        "linear-gradient(180deg, rgba(2,8,23,0.30) 0%, rgba(2,8,23,0) 48%, rgba(2,8,23,0.36) 100%)",
    },
  }),
  h(
    "div",
    {
      style: {
        position: "relative",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        width: "100%",
        height: "100%",
        padding: "64px 68px 62px",
      },
    },
    brand,
    headline
  )
)

const response = new ImageResponse(element, { width: 1200, height: 630 })
const output = Buffer.from(await response.arrayBuffer())
const outputPath = join(publicDir, "og.png")
writeFileSync(outputPath, output)
console.log("WROTE", outputPath, output.length, "bytes")
