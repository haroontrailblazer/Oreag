# Oreag identity

The approved context-loop symbol is shared by the app, auth cards, browser icons, and social previews. The app wordmark uses its existing Geist font. Both symbol and wordmark follow the foreground color, with no badge background or shadow.

## Source and exports

- `oreag-context-loop-v1.png`: approved reference.
- `oreag-symbol-source.png`: transparent symbol extracted with the built-in image generation tool.
- `frontend/public/brand/oreag-symbol.png`: normalized transparent dark mark, 1024px.
- `frontend/public/brand/oreag-symbol-light.png`: matching light mark.
- `frontend/src/app/icon.svg`: adaptive browser icon. This SVG embeds the raster mark to preserve the approved contour; it is not a traced vector master.
- `frontend/src/app/favicon.ico`: transparent 16, 32, 48, 64, 128 and 256px entries.
- `frontend/src/app/apple-icon.png`: transparent 180px touch icon.
- `frontend/public/brand/icon-{16,32,48,192,512}.png`: additional icon exports.
- `frontend/public/oreag-og-context-loop.jpg` and `oreag-og-context-loop-light.jpg`: 1200 × 630 social previews. Shared metadata serves the dark version with its existing content-hash cache busting. Legacy social-image paths also use the new branding.

Run from `frontend`:

```sh
node scripts/generate-brand-assets.mjs
node scripts/generate-og.mjs
```

## Transparent extraction prompt

Edit this approved Oreag logo image for use as the app's production icon. Background extraction only. Preserve the EXACT black abstract three-band context-loop symbol: same three silhouettes, curves, central aperture, proportions, stroke weight, orientation, and gaps. Remove the word Oreag below it and remove ALL white background including the central aperture and the channels between the three bands. Output the SYMBOL ONLY as opaque solid near-black (#111111) on a genuinely transparent alpha background, not a checkerboard painted into an image. Do not redesign, reinterpret, add, or round any detail. Crop to a square with the symbol centered and an even clear margin of about 6% on each side. No text, no shadows, no glow, no grain or textures. This must faithfully extract the approved mark, with crisp antialiased edges and genuine transparent pixels everywhere outside the symbol.
