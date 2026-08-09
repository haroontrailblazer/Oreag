"use client"

import { useEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"

const CHARACTER_SET =
  "0123456789qwertyuiopasdfghjklzxcvbnm!?></\\a~+*=@#$%".split("")

function generateRandomString(length: number): string {
  let randomString = ""
  for (let index = 0; index < length; index += 1) {
    randomString +=
      CHARACTER_SET[Math.floor(Math.random() * CHARACTER_SET.length)]
  }
  return randomString
}

export interface TextScrambleEffectProps {
  text?: string
  className?: string
}

/**
 * Briefly resolves random glyphs into the supplied text.
 *
 * The final value remains in the accessibility tree while the animated glyphs
 * are decorative. An invisible copy anchors the final width, preventing usage
 * cards from shifting as narrow and wide characters swap during the reveal.
 */
export function TextScrambleEffect({
  text = "",
  className,
}: TextScrambleEffectProps) {
  const [displayText, setDisplayText] = useState<[string, string]>([text, ""])
  const animationFrameRef = useRef<number | null>(null)
  const progressRef = useRef(0)

  useEffect(() => {
    if (animationFrameRef.current != null) {
      cancelAnimationFrame(animationFrameRef.current)
    }

    if (
      !text ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      animationFrameRef.current = requestAnimationFrame(() => {
        setDisplayText([text, ""])
        animationFrameRef.current = null
      })
      return () => {
        if (animationFrameRef.current != null) {
          cancelAnimationFrame(animationFrameRef.current)
        }
      }
    }

    progressRef.current = 0
    const scrambleFrames = 18
    const revealFrameInterval = 2

    const animateTextReveal = () => {
      const progress = progressRef.current

      if (progress < scrambleFrames) {
        setDisplayText(["", generateRandomString(text.length)])
      } else {
        const revealedLength = Math.min(
          text.length,
          Math.floor((progress - scrambleFrames) / revealFrameInterval)
        )

        if (revealedLength >= text.length) {
          setDisplayText([text, ""])
          animationFrameRef.current = null
          return
        }

        const revealedPart = text.slice(0, revealedLength)
        setDisplayText([
          revealedPart,
          generateRandomString(text.length - revealedPart.length),
        ])
      }

      progressRef.current += 1
      animationFrameRef.current = requestAnimationFrame(animateTextReveal)
    }

    animationFrameRef.current = requestAnimationFrame(animateTextReveal)

    return () => {
      if (animationFrameRef.current != null) {
        cancelAnimationFrame(animationFrameRef.current)
      }
    }
  }, [text])

  return (
    <span
      className={cn("inline-grid max-w-full", className)}
      aria-label={text}
      title={text}
    >
      <span
        aria-hidden="true"
        className="col-start-1 row-start-1 overflow-hidden whitespace-nowrap"
      >
        <span>{displayText[0]}</span>
        <span className="text-muted-foreground/55">{displayText[1]}</span>
      </span>
      <span
        aria-hidden="true"
        className="invisible col-start-1 row-start-1 whitespace-nowrap"
      >
        {text}
      </span>
    </span>
  )
}

export default TextScrambleEffect
