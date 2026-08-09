import { createHash } from "node:crypto"
import { readFileSync } from "node:fs"
import { join } from "node:path"

/**
 * The social preview image, with a cache-busting version derived from its own
 * CONTENT.
 *
 * WHY THIS EXISTS
 *
 * WhatsApp, LinkedIn and Facebook cache a preview against the image URL and
 * re-fetch only when that URL changes. Replacing the artwork at the same path
 * therefore changes nothing they can see: they keep serving the render they
 * already have, which looks exactly like "my new image did not upload".
 *
 * The previous workaround was renaming the file by hand - og.png, then
 * oreag-og-v2.jpg, then oreag-og-whatsapp-v3.jpg. That works exactly once per
 * rename and silently stops working the moment someone edits the art without
 * bumping the name, which is the failure this replaces. Hashing the bytes makes
 * the bust automatic: new pixels, new URL, always.
 *
 * Read at build time in a Server Component, so there is no generated file to
 * keep in sync and no way for the version to drift from the image it names.
 * Falls back to the bare path if the read fails - a preview with a stale
 * version is far better than a build that dies over a cache-busting nicety.
 */
export const OG_IMAGE_FILE = "oreag-og-whatsapp-v3.jpg"
export const OG_IMAGE_WIDTH = 1200
export const OG_IMAGE_HEIGHT = 630
export const OG_IMAGE_TYPE = "image/jpeg"
export const OG_IMAGE_ALT =
  "Oreag above a painterly night scene of a person working through documents"

function contentVersion(): string {
  try {
    const bytes = readFileSync(join(process.cwd(), "public", OG_IMAGE_FILE))
    return createHash("sha1").update(bytes).digest("hex").slice(0, 8)
  } catch {
    return ""
  }
}

/** Absolute-path URL for the OG image, versioned by content. */
export function ogImagePath(): string {
  const version = contentVersion()
  return version ? `/${OG_IMAGE_FILE}?v=${version}` : `/${OG_IMAGE_FILE}`
}


/**
 * The `openGraph.images` array, ready to spread into any page's metadata.
 *
 * Next.js REPLACES an inherited `openGraph` block rather than deep-merging it:
 * the moment a page declares its own `openGraph` (say, to fix its title), the
 * root layout's `images` vanish and that page shares with no picture at all.
 * That is not obvious, and it is silent - the page still renders a correct
 * <title>. Every page that sets openGraph must therefore restate the images,
 * and this is the one definition they all restate from.
 */
export function ogImages() {
  const path = ogImagePath()
  return [
    {
      url: path,
      secureUrl: `https://oreag.vercel.app${path}`,
      width: OG_IMAGE_WIDTH,
      height: OG_IMAGE_HEIGHT,
      type: OG_IMAGE_TYPE,
      alt: OG_IMAGE_ALT,
    },
  ]
}
