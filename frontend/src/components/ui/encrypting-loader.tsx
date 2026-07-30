"use client"

import { useEffect, useState } from "react"

const CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

function code(): string {
  const pick = (n: number) =>
    Array.from(
      { length: n },
      () => CHARS[Math.floor(Math.random() * CHARS.length)]
    ).join("")
  return `${pick(4)}-${pick(2)}-${pick(4)}`
}

/** Lottielab "Data | Encrypting"-style loader: rows of monospace codes with a
 * single highlighted row scrambling its characters, and a mono pill label -
 * in the app's sky accent. Shown while provider API keys are encrypted and
 * stored (account and project level). */
export function EncryptingLoader({
  rows = 4,
  label = "Encrypting...",
}: {
  rows?: number
  label?: string
}) {
  const [lines, setLines] = useState<string[]>(() =>
    Array.from({ length: rows }, code)
  )
  const [active, setActive] = useState(0)

  // One timer drives both the highlighted row and its scrambling. Doing it in
  // the interval callback rather than in a second effect keyed on a tick
  // counter avoids a setState in an effect body, which cascades an extra
  // render per frame (react-hooks/set-state-in-effect).
  useEffect(() => {
    let tick = 0
    const id = setInterval(() => {
      tick += 1
      // Each row holds for 4 frames before the highlight moves on.
      const row = Math.floor(tick / 4) % rows
      setActive(row)
      setLines((prev) => prev.map((l, i) => (i === row ? code() : l)))
    }, 90)
    return () => clearInterval(id)
  }, [rows])

  return (
    <div className="flex flex-col items-center gap-4 py-4">
      <div
        className="flex flex-col gap-1 text-center font-mono text-sm tracking-[0.18em]"
        aria-hidden="true"
      >
        {lines.map((l, i) => (
          <span
            key={i}
            className={
              i === active
                ? "text-zinc-800 dark:text-zinc-100"
                : "text-muted-foreground/50"
            }
          >
            {l}
          </span>
        ))}
      </div>
      <span className="rounded-full border bg-background px-3 py-1 font-mono text-[11px] text-zinc-700 dark:text-zinc-100">
        {label}
      </span>
    </div>
  )
}
