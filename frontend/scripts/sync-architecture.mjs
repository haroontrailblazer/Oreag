// Publish the LikeC4 architecture model: the raw source AND the interactive
// viewer that renders it.
//
// Runs automatically before `npm run build` (npm's `prebuild` hook).
//
// WHY A COPY OF THE SOURCE AT ALL
//
// oreag_1.c4 lives at the repo root - it describes the whole system, backend
// included, and scripts/check_docs_sync.py validates it there. Vercel builds
// with the frontend as its root directory, and whether files ABOVE that root
// are present depends on a project setting that is easy to have off. Relying on
// `../oreag_1.c4` existing at build time would mean the page 404s in production
// while working perfectly on a laptop.
//
// So a copy is committed under public/, this script refreshes it whenever the
// source is reachable, and check_docs_sync.py fails when the two disagree -
// which is what keeps a committed copy from going stale.
//
// THE VIEWER
//
// `likec4 build` renders the model into a static SPA. Built from the COPY, not
// the root source, so it works identically on Vercel whether or not files above
// the root directory came along.
//
// --use-hash-history is what makes it survive static hosting: without it the
// app's routes are real paths like /architecture/view/api, which do not exist
// as files and 404 on a CDN unless every one of them is rewritten. With hashes
// there is exactly one real file and the router does the rest.
import { execFileSync } from "node:child_process"
import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const frontend = join(here, "..")
const source = join(frontend, "..", "oreag_1.c4")
const published = join(frontend, "public", "architecture.c4")
const viewerDir = join(frontend, "public", "architecture")

// ── 1. the raw model ────────────────────────────────────────────────────────
if (existsSync(source)) {
  const changed =
    !existsSync(published) ||
    readFileSync(source, "utf8") !== readFileSync(published, "utf8")
  if (changed) {
    mkdirSync(dirname(published), { recursive: true })
    copyFileSync(source, published)
    console.log("[architecture] refreshed public/architecture.c4")
  } else {
    console.log("[architecture] public/architecture.c4 already current")
  }
} else {
  // Expected on Vercel when files outside the root directory are excluded. The
  // committed copy is the fallback, and check_docs_sync.py verifies it is in
  // sync, so this is not a silent degradation.
  console.log("[architecture] source not reachable - using the committed copy")
}

if (!existsSync(published)) {
  console.error("[architecture] no model to build from - viewer skipped")
  process.exit(0)
}

// ── 2. the viewer ───────────────────────────────────────────────────────────
// Built into a directory containing ONLY the model, so likec4 does not walk
// public/ (and its own previous output) looking for sources.
const staging = join(frontend, ".likec4-src")
rmSync(staging, { recursive: true, force: true })
mkdirSync(staging, { recursive: true })
copyFileSync(published, join(staging, "oreag.c4"))

try {
  rmSync(viewerDir, { recursive: true, force: true })
  // The package's own entry, run with THIS node - not `npx`. Node refuses to
  // spawn a .cmd shim without a shell on Windows (EINVAL, a deliberate fix for
  // CVE-2024-27980), and going through a shell to work around that would mean
  // quoting arguments differently per platform.
  const likec4 = join(frontend, "node_modules", "likec4", "bin", "likec4.mjs")
  if (!existsSync(likec4)) {
    throw new Error(`likec4 is not installed at ${likec4}`)
  }
  execFileSync(
    process.execPath,
    [
      likec4,
      "build",
      staging,
      "-o",
      viewerDir,
      "--base",
      "/architecture/",
      "--use-hash-history",
    ],
    { cwd: frontend, stdio: "inherit" }
  )
  console.log("[architecture] built the viewer at /architecture/")
} catch (error) {
  // A broken diagram must not block shipping the product. The raw model is
  // still served at /architecture.c4, and the docs link degrades to that.
  console.error(
    "[architecture] viewer build FAILED - /architecture.c4 still serves the model"
  )
  console.error(String(error?.message ?? error))
} finally {
  rmSync(staging, { recursive: true, force: true })
}
