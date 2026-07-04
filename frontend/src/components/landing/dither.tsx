"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { Canvas, useFrame, useThree } from "@react-three/fiber"
import { EffectComposer, wrapEffect } from "@react-three/postprocessing"
import { Effect } from "postprocessing"
import * as THREE from "three"

// The landing hero painting, dithered: hero.jpg is drawn cover-fit on a
// full-bleed plane with the Starry Night sky band swirled by animated perlin
// noise (the same motion the old SVG displacement filter gave it), then the
// whole frame is quantized through an ordered 8x8 Bayer dither for the retro
// look. Tuned against CPU-rendered previews of the exact same math.

const vertexShader = `
precision highp float;
varying vec2 vUv;
void main() {
  vUv = uv;
  vec4 modelPosition = modelMatrix * vec4(position, 1.0);
  vec4 viewPosition = viewMatrix * modelPosition;
  gl_Position = projectionMatrix * viewPosition;
}
`

const paintingFragmentShader = `
precision highp float;
uniform sampler2D map;
uniform vec2 resolution;
uniform vec2 texResolution;
uniform float time;
uniform float swirlStrength;
uniform float swirlFrequency;
varying vec2 vUv;

vec4 mod289(vec4 x) { return x - floor(x * (1.0/289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
vec2 fade(vec2 t) { return t*t*t*(t*(t*6.0-15.0)+10.0); }

float cnoise(vec2 P) {
  vec4 Pi = floor(P.xyxy) + vec4(0.0,0.0,1.0,1.0);
  vec4 Pf = fract(P.xyxy) - vec4(0.0,0.0,1.0,1.0);
  Pi = mod289(Pi);
  vec4 ix = Pi.xzxz;
  vec4 iy = Pi.yyww;
  vec4 fx = Pf.xzxz;
  vec4 fy = Pf.yyww;
  vec4 i = permute(permute(ix) + iy);
  vec4 gx = fract(i * (1.0/41.0)) * 2.0 - 1.0;
  vec4 gy = abs(gx) - 0.5;
  vec4 tx = floor(gx + 0.5);
  gx = gx - tx;
  vec2 g00 = vec2(gx.x, gy.x);
  vec2 g10 = vec2(gx.y, gy.y);
  vec2 g01 = vec2(gx.z, gy.z);
  vec2 g11 = vec2(gx.w, gy.w);
  vec4 norm = taylorInvSqrt(vec4(dot(g00,g00), dot(g01,g01), dot(g10,g10), dot(g11,g11)));
  g00 *= norm.x; g01 *= norm.y; g10 *= norm.z; g11 *= norm.w;
  float n00 = dot(g00, vec2(fx.x, fy.x));
  float n10 = dot(g10, vec2(fx.y, fy.y));
  float n01 = dot(g01, vec2(fx.z, fy.z));
  float n11 = dot(g11, vec2(fx.w, fy.w));
  vec2 fade_xy = fade(Pf.xy);
  vec2 n_x = mix(vec2(n00, n01), vec2(n10, n11), fade_xy.x);
  return 2.3 * mix(n_x.x, n_x.y, fade_xy.y);
}

void main() {
  // object-fit: cover - crop the texture to the panel without distortion.
  float canvasAspect = resolution.x / max(resolution.y, 1.0);
  float texAspect = texResolution.x / max(texResolution.y, 1.0);
  vec2 scale = canvasAspect > texAspect
    ? vec2(1.0, texAspect / canvasAspect)
    : vec2(canvasAspect / texAspect, 1.0);
  vec2 uv = (vUv - 0.5) * scale + 0.5;

  // Sky band of the PANEL swirls: full above 70% height, fading in from 56%
  // (the old CSS mask ran "solid to 30% from the top, transparent by 44%").
  float m = smoothstep(0.56, 0.70, vUv.y);

  vec2 p = uv * swirlFrequency;
  vec2 flow = vec2(
    cnoise(p + vec2(time * 0.30, 0.0)),
    cnoise(p + vec2(19.19, 7.3) - vec2(0.0, time * 0.24))
  );
  vec2 displaced = uv + flow * swirlStrength * m;

  gl_FragColor = texture2D(map, displaced);
}
`

const ditherFragmentShader = `
precision highp float;
uniform float colorNum;
uniform float pixelSize;
const float bayerMatrix8x8[64] = float[64](
  0.0/64.0, 48.0/64.0, 12.0/64.0, 60.0/64.0,  3.0/64.0, 51.0/64.0, 15.0/64.0, 63.0/64.0,
  32.0/64.0,16.0/64.0, 44.0/64.0, 28.0/64.0, 35.0/64.0,19.0/64.0, 47.0/64.0, 31.0/64.0,
  8.0/64.0, 56.0/64.0,  4.0/64.0, 52.0/64.0, 11.0/64.0,59.0/64.0,  7.0/64.0, 55.0/64.0,
  40.0/64.0,24.0/64.0, 36.0/64.0, 20.0/64.0, 43.0/64.0,27.0/64.0, 39.0/64.0, 23.0/64.0,
  2.0/64.0, 50.0/64.0, 14.0/64.0, 62.0/64.0,  1.0/64.0,49.0/64.0, 13.0/64.0, 61.0/64.0,
  34.0/64.0,18.0/64.0, 46.0/64.0, 30.0/64.0, 33.0/64.0,17.0/64.0, 45.0/64.0, 29.0/64.0,
  10.0/64.0,58.0/64.0,  6.0/64.0, 54.0/64.0,  9.0/64.0,57.0/64.0,  5.0/64.0, 53.0/64.0,
  42.0/64.0,26.0/64.0, 38.0/64.0, 22.0/64.0, 41.0/64.0,25.0/64.0, 37.0/64.0, 21.0/64.0
);

vec3 dither(vec2 uv, vec3 color) {
  vec2 scaledCoord = floor(uv * resolution / pixelSize);
  int x = int(mod(scaledCoord.x, 8.0));
  int y = int(mod(scaledCoord.y, 8.0));
  float threshold = bayerMatrix8x8[y * 8 + x] - 0.25;
  float step = 1.0 / (colorNum - 1.0);
  color += threshold * step;
  float bias = 0.08;
  color = clamp(color - bias, 0.0, 1.0);
  return floor(color * (colorNum - 1.0) + 0.5) / (colorNum - 1.0);
}

void mainImage(in vec4 inputColor, in vec2 uv, out vec4 outputColor) {
  vec2 normalizedPixelSize = pixelSize / resolution;
  vec2 uvPixel = normalizedPixelSize * floor(uv / normalizedPixelSize);
  vec4 color = texture2D(inputBuffer, uvPixel);
  // Quantize in gamma space so the levels are perceptually even (the composer
  // buffer is linear; the final pass re-encodes to sRGB after this effect).
  vec3 srgb = pow(max(color.rgb, vec3(0.0)), vec3(1.0/2.2));
  srgb = dither(uv, srgb);
  color.rgb = pow(srgb, vec3(2.2));
  outputColor = color;
}
`

class RetroEffectImpl extends Effect {
  constructor() {
    super("RetroEffect", ditherFragmentShader, {
      uniforms: new Map<string, THREE.Uniform<number>>([
        ["colorNum", new THREE.Uniform(4)],
        ["pixelSize", new THREE.Uniform(2)],
      ]),
    })
  }
  // wrapEffect spreads JSX props onto the instance, so these run on prop change.
  set colorNum(v: number) {
    this.uniforms.get("colorNum")!.value = v
  }
  get colorNum(): number {
    return this.uniforms.get("colorNum")!.value as number
  }
  set pixelSize(v: number) {
    this.uniforms.get("pixelSize")!.value = v
  }
  get pixelSize(): number {
    return this.uniforms.get("pixelSize")!.value as number
  }
}

const RetroEffect = wrapEffect(RetroEffectImpl)

interface PaintingUniforms {
  [uniform: string]: THREE.IUniform
  map: THREE.IUniform<THREE.Texture>
  resolution: THREE.IUniform<THREE.Vector2>
  texResolution: THREE.IUniform<THREE.Vector2>
  time: THREE.IUniform<number>
  swirlStrength: THREE.IUniform<number>
  swirlFrequency: THREE.IUniform<number>
}

interface DitherProps {
  src: string
  colorNum?: number
  pixelSize?: number
  swirlStrength?: number
  swirlFrequency?: number
  disableAnimation?: boolean
}

function DitheredPainting({
  src,
  colorNum,
  pixelSize,
  swirlStrength,
  swirlFrequency,
  disableAnimation,
}: Required<DitherProps>) {
  const materialRef = useRef<THREE.ShaderMaterial>(null)
  const { viewport, size, gl } = useThree()
  const [texture, setTexture] = useState<THREE.Texture | null>(null)

  useEffect(() => {
    let cancelled = false
    let loaded: THREE.Texture | null = null
    new THREE.TextureLoader().load(src, (tex) => {
      if (cancelled) {
        tex.dispose()
        return
      }
      tex.colorSpace = THREE.SRGBColorSpace
      loaded = tex
      setTexture(tex)
    })
    return () => {
      cancelled = true
      loaded?.dispose()
      setTexture(null)
    }
  }, [src])

  // Initial uniform objects for material creation; every later update goes
  // through materialRef (three mutates uniform .value in place each frame).
  const initialUniforms = useMemo<PaintingUniforms | null>(() => {
    if (!texture) return null
    const image = texture.image as { width: number; height: number }
    return {
      map: new THREE.Uniform(texture),
      resolution: new THREE.Uniform(new THREE.Vector2(0, 0)),
      texResolution: new THREE.Uniform(new THREE.Vector2(image.width, image.height)),
      time: new THREE.Uniform(0),
      swirlStrength: new THREE.Uniform(0),
      swirlFrequency: new THREE.Uniform(0),
    }
  }, [texture])

  useEffect(() => {
    const material = materialRef.current
    if (!material) return
    const dpr = gl.getPixelRatio()
    const w = Math.floor(size.width * dpr)
    const h = Math.floor(size.height * dpr)
    const res = (material.uniforms as unknown as PaintingUniforms).resolution.value
    if (res.x !== w || res.y !== h) {
      res.set(w, h)
    }
  }, [size, gl, texture])

  useFrame(({ clock }) => {
    const material = materialRef.current
    if (!material) return
    const u = material.uniforms as unknown as PaintingUniforms

    if (!disableAnimation) {
      u.time.value = clock.getElapsedTime()
    }
    if (u.swirlStrength.value !== swirlStrength) u.swirlStrength.value = swirlStrength
    if (u.swirlFrequency.value !== swirlFrequency) u.swirlFrequency.value = swirlFrequency
  })

  return (
    <>
      {texture && initialUniforms && (
        <mesh scale={[viewport.width, viewport.height, 1]}>
          <planeGeometry args={[1, 1]} />
          <shaderMaterial
            ref={materialRef}
            vertexShader={vertexShader}
            fragmentShader={paintingFragmentShader}
            uniforms={initialUniforms}
          />
        </mesh>
      )}

      <EffectComposer>
        <RetroEffect colorNum={colorNum} pixelSize={pixelSize} />
      </EffectComposer>
    </>
  )
}

export default function Dither({
  src,
  colorNum = 4,
  pixelSize = 2,
  swirlStrength = 0.015,
  swirlFrequency = 9,
  disableAnimation = false,
}: DitherProps) {
  return (
    <Canvas
      className="h-full w-full"
      camera={{ position: [0, 0, 6] }}
      dpr={1}
      gl={{ antialias: true, preserveDrawingBuffer: true }}
    >
      <DitheredPainting
        src={src}
        colorNum={colorNum}
        pixelSize={pixelSize}
        swirlStrength={swirlStrength}
        swirlFrequency={swirlFrequency}
        disableAnimation={disableAnimation}
      />
    </Canvas>
  )
}
