// Export deployment-ready sizes from the approved transparent logo.
// Run from frontend: node scripts/generate-brand-assets.mjs
import { writeFileSync, mkdirSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import sharp from "sharp"

const frontend = join(dirname(fileURLToPath(import.meta.url)), "..")
const publicDir = join(frontend, "public")
const brandDir = join(publicDir, "brand")
const appDir = join(frontend, "src", "app")
mkdirSync(brandDir, { recursive: true })
const source = join(frontend, "..", "design", "branding", "oreag-symbol-source.png")

// Equal optical clear space for every export; retain the approved alpha edges.
const mask = await sharp(source).trim().resize(896, 896, { fit: "contain", background: "#00000000" })
  .extend({ top: 64, bottom: 64, left: 64, right: 64, background: "#00000000" })
  .extractChannel("alpha").png().toBuffer()
async function ink(color) {
  return sharp({ create: { width: 1024, height: 1024, channels: 3, background: color } })
    .joinChannel(mask).png().toBuffer()
}
const dark = await ink("#111111")
const light = await ink("#fafafa")
writeFileSync(join(brandDir, "oreag-symbol.png"), dark)
writeFileSync(join(brandDir, "oreag-symbol-light.png"), light)
writeFileSync(join(publicDir, "logo.png"), dark)

const image = '<image width="1024" height="1024" href="data:image/png;base64,' + dark.toString("base64") + '"/>'
const start = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
writeFileSync(join(publicDir, "logo.svg"), start + image + "</svg>")
writeFileSync(join(appDir, "icon.svg"), start + "<style>@media(prefers-color-scheme:dark){image{filter:invert(1)}}</style>" + image + "</svg>")

for (const size of [16, 32, 48, 192, 512]) {
  await sharp(dark).resize(size, size).png().toFile(join(brandDir, "icon-" + size + ".png"))
}
await sharp(dark).resize(180, 180).png().toFile(join(appDir, "apple-icon.png"))

// ICO container with PNG entries, supported by modern Windows/browser decoders.
const sizes = [16, 32, 48, 64, 128, 256]
const entries = await Promise.all(sizes.map(size => sharp(dark).resize(size, size).png().toBuffer()))
const header = Buffer.alloc(6 + 16 * entries.length)
header.writeUInt16LE(1, 2)
header.writeUInt16LE(entries.length, 4)
let offset = header.length
entries.forEach((bytes, index) => {
  const entry = 6 + 16 * index
  header[entry] = sizes[index] === 256 ? 0 : sizes[index]
  header[entry + 1] = header[entry]
  header.writeUInt16LE(1, entry + 4)
  header.writeUInt16LE(32, entry + 6)
  header.writeUInt32LE(bytes.length, entry + 8)
  header.writeUInt32LE(offset, entry + 12)
  offset += bytes.length
})
writeFileSync(join(appDir, "favicon.ico"), Buffer.concat([header, ...entries]))
console.log("Exported transparent mark, light variant, adaptive favicon, Apple icon, and six ICO sizes.")
