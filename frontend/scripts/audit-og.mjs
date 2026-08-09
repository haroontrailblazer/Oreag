// Audit every prerendered page for a complete social preview.
//
//   npm run build && node scripts/audit-og.mjs
//
// WHY THIS EXISTS
//
// Next.js REPLACES an inherited `openGraph` block rather than deep-merging it.
// The moment a page declares its own - say, to fix a wrong share title - the
// root layout's `images` disappear and that page shares with no picture at all.
// Nothing warns you: the page still renders a correct <title>, the build stays
// green, and you only find out when someone pastes the link into WhatsApp.
//
// That regression happened while fixing /docs. This is the check that catches
// it, and it reads the BUILT html rather than the source, so it verifies what
// crawlers will actually receive.
import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"

const ROOT = ".next/server/app"

// Next.js internals, not shareable URLs. _not-found is deliberately NOT here:
// a 404 is a real page someone can land on and paste.
const INTERNAL = new Set(["/_global-error"])

const REQUIRED = ["og:title", "og:description", "og:image"]

function pages(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) pages(path, out)
    else if (entry.endsWith(".html")) out.push(path)
  }
  return out
}

function meta(html, property) {
  const match = html.match(
    new RegExp(`<meta property="${property}" content="([^"]*)"`)
  )
  return match ? match[1] : null
}

const found = pages(ROOT).sort()
if (found.length === 0) {
  console.error("No built pages found - run `npm run build` first.")
  process.exit(2)
}

const problems = []
console.log(`Auditing ${found.length} prerendered pages\n`)

for (const file of found) {
  // Normalise separators FIRST: on Windows the walk yields backslashes, so
  // stripping a forward-slash ROOT silently did nothing and every route kept
  // its full path - which made the internal-page skip never match.
  const route =
    file.replace(/\\/g, "/").replace(ROOT, "").replace(/\.html$/, "") || "/"
  if (INTERNAL.has(route)) continue

  const html = readFileSync(file, "utf8")
  const missing = REQUIRED.filter((tag) => !meta(html, tag))
  const image = meta(html, "og:image")

  // A relative og:image is the classic silent failure: crawlers do not resolve
  // it, so the preview simply has no picture.
  if (image && !image.startsWith("http")) {
    missing.push("og:image is not absolute")
  }
  // Without a version the platforms keep serving whatever they cached the
  // first time, so replacing the artwork appears to do nothing.
  if (image && !image.includes("?v=")) {
    missing.push("og:image has no content version")
  }

  if (missing.length) problems.push({ route, missing })
  console.log(
    `  ${missing.length ? "FAIL" : "ok  "}  ${route.padEnd(32)} ${
      image ? image.replace(/^https?:\/\/[^/]+/, "") : "(no image)"
    }`
  )
}

if (problems.length) {
  console.log("\nProblems:")
  for (const { route, missing } of problems) {
    console.log(`  ${route}: ${missing.join(", ")}`)
  }
  console.log(
    "\nA page that sets its own openGraph must restate images - use ogImages()."
  )
  process.exit(1)
}
console.log("\nEvery shareable page has a complete, absolute, versioned preview.")
