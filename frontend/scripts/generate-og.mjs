// Rebuild both social-preview themes from the same production logo.
// Run: node scripts/generate-og.mjs
import { readFileSync, writeFileSync } from "node:fs"
import { createRequire } from "node:module"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import React from "react"

const here = dirname(fileURLToPath(import.meta.url))
const publicDir = join(here, "..", "public")
const require = createRequire(import.meta.url)
const { ImageResponse } = require("next/dist/server/og/image-response.js")
const sharp = require("sharp")
const h = React.createElement

for (const theme of ["dark", "light"]) {
  const dark = theme === "dark"
  const ink = dark ? "#fafafa" : "#111111"
  const muted = dark ? "#a3a3a3" : "#636363"
  const rule = dark ? "#303030" : "#dedede"
  const iconSrc = "data:image/png;base64," + readFileSync(join(publicDir, "brand", dark ? "oreag-symbol-light.png" : "oreag-symbol.png")).toString("base64")
  const element = h("div", {
    style: { width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between", padding: "64px 72px", background: dark ? "#111111" : "#fafafa", color: ink, fontFamily: "sans-serif" },
  },
    h("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between" } },
      h("div", { style: { display: "flex", alignItems: "center", gap: "16px" } },
        h("img", { src: iconSrc, width: 64, height: 64 }),
        h("span", { style: { fontSize: 48, fontWeight: 700, letterSpacing: "-2px" } }, "Oreag")),
      h("span", { style: { fontSize: 18, color: muted } }, "RAG & MEMORY")
    ),
    h("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 48 } },
      h("div", { style: { display: "flex", flexDirection: "column", gap: 22, maxWidth: 740 } },
        h("div", { style: { display: "flex", flexDirection: "column", fontSize: 66, fontWeight: 700, letterSpacing: "-3px", lineHeight: 1.08 } },
          h("span", null, "Your knowledge."),
          h("span", null, "Ready for every answer.")),
        h("span", { style: { fontSize: 23, color: muted, lineHeight: 1.5 } }, "Grounded RAG APIs and persistent memory for your apps and agents.")
      ),
      h("img", { src: iconSrc, width: 200, height: 200 })
    ),
    h("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", borderTop: "1px solid " + rule, paddingTop: 22, fontSize: 17, color: muted } },
      h("span", null, "Documents → Knowledge → Answers"),
      h("span", null, "oreag.vercel.app"))
  )
  const response = new ImageResponse(element, { width: 1200, height: 630 })
  const output = await sharp(Buffer.from(await response.arrayBuffer()))
    .jpeg({ quality: 88, progressive: false, chromaSubsampling: "4:2:0" }).toBuffer()
  const filename = dark ? "oreag-og-context-loop.jpg" : "oreag-og-context-loop-light.jpg"
  writeFileSync(join(publicDir, filename), output)
  // Older shared image URLs also receive the approved branding.
  if (dark) for (const legacy of ["oreag-og-v2.jpg", "oreag-og-whatsapp-v3.jpg"]) writeFileSync(join(publicDir, legacy), output)
  console.log("WROTE", filename, output.length, "bytes")
}
