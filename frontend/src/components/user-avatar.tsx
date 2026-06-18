"use client"

import { useState } from "react"

import { cn } from "@/lib/utils"

/** Round avatar that shows `src` and falls back to an initial if it fails/absent.
 * Pass a changing `key` (e.g. key={src}) when the src can change at runtime. */
export function UserAvatar({
  src,
  name,
  className,
}: {
  src?: string | null
  name?: string | null
  className?: string
}) {
  const [ok, setOk] = useState(true)
  const initial = (name?.trim()?.[0] ?? "?").toUpperCase()
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-sidebar-accent font-semibold ring-1 ring-border",
        className
      )}
    >
      {src && ok ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt=""
          className="size-full object-cover"
          onError={() => setOk(false)}
        />
      ) : (
        <span>{initial}</span>
      )}
    </span>
  )
}
