// Publish the LikeC4 architecture model as a static asset.
//
// Runs automatically before `npm run build` (npm's `prebuild` hook).
//
// WHY A COPY AT ALL
//
// oreag_1.c4 lives at the repo root - it describes the whole system, backend
// included, and scripts/check_docs_sync.py validates it there. Vercel builds
// with the frontend as its root directory, and whether files ABOVE that root
// are present in the build depends on a project setting that is easy to have
// off. Relying on `../oreag_1.c4` existing at build time would mean the page
// 404s in production while working perfectly on a laptop.
//
// So a copy is committed under public/, and this script refreshes it whenever
// the source is reachable. check_docs_sync.py fails the build if the two ever
// disagree, which is what keeps a committed copy from going stale.
import { copyFileSync, existsSync, readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const source = join(here, "..", "..", "oreag_1.c4")
const published = join(here, "..", "public", "architecture.c4")

if (!existsSync(source)) {
  // Expected on Vercel when files outside the root directory are excluded.
  // The committed copy is the fallback, and it is verified in sync by
  // scripts/check_docs_sync.py, so this is not a silent degradation.
  console.log("[architecture] source not reachable - using the committed copy")
  process.exit(0)
}

if (
  existsSync(published) &&
  readFileSync(source, "utf8") === readFileSync(published, "utf8")
) {
  console.log("[architecture] public/architecture.c4 already current")
  process.exit(0)
}

copyFileSync(source, published)
console.log("[architecture] refreshed public/architecture.c4 from oreag_1.c4")
