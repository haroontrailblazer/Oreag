// Render the LikeC4 model into the interactive viewer served at /architecture.
//
// Runs automatically before `npm run build` (npm's `prebuild` hook).
//
// ONE MODEL, ONE PLACE
//
// public/architecture.c4 is the source of truth and the published artifact at
// once: it is served as-is at /architecture.c4 and it is what this script
// renders. There is deliberately no second copy anywhere in the repo - the
// LikeC4 tooling treats every .c4 file in a workspace as one project, so a
// duplicate declares every element and every specification twice and fills
// BOTH files with duplicate-declaration errors in the editor.
//
// Living under public/ also removes a whole class of deployment problem: Vercel
// builds with the frontend as its root directory, and files above that root are
// only present if a project setting says so. A model inside frontend/ is always
// there.
//
// --use-hash-history is what makes the viewer survive static hosting. Without
// it the app's routes are real paths like /architecture/view/api, which do not
// exist as files and 404 on a CDN unless every one of them is rewritten. With
// hashes there is exactly one real file and the router does the rest.
import { execFileSync } from "node:child_process"
import { copyFileSync, existsSync, mkdirSync, rmSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const frontend = join(here, "..")
const model = join(frontend, "public", "architecture.c4")
const viewerDir = join(frontend, "public", "architecture")

if (!existsSync(model)) {
  // Not fatal: the product ships without a diagram far more happily than it
  // ships not at all. scripts/check_docs_sync.py is what fails on this.
  console.error(`[architecture] ${model} is missing - viewer skipped`)
  process.exit(0)
}

// Built from a staging directory holding ONLY the model, so likec4 does not
// walk public/ - which contains its own previous output.
const staging = join(frontend, ".likec4-src")
rmSync(staging, { recursive: true, force: true })
mkdirSync(staging, { recursive: true })
copyFileSync(model, join(staging, "oreag.c4"))

try {
  rmSync(viewerDir, { recursive: true, force: true })
  // The package's own entry, run with THIS node - not `npx`. Node refuses to
  // spawn a .cmd shim without a shell on Windows (EINVAL, the fix for
  // CVE-2024-27980), and going through a shell would mean quoting arguments
  // differently per platform.
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
  // still served at /architecture.c4.
  console.error(
    "[architecture] viewer build FAILED - /architecture.c4 still serves the model"
  )
  console.error(String(error?.message ?? error))
} finally {
  rmSync(staging, { recursive: true, force: true })
}
