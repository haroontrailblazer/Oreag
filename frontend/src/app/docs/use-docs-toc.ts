"use client"

import { useEffect, useState } from "react"

export type TocItem = { id: string; text: string }
export type TocSection = { id: string; title: string; items: TocItem[] }

/**
 * Reads the rendered headings inside #docs-content (H2 = topic, H3 = sub-topic)
 * into a nested table of contents, and scroll-spies them. Shared by the left
 * sidebar and the right "On this page" panel so both highlight the same active
 * heading. Reading the DOM keeps the TOC and the real anchors perfectly in sync.
 */
export function useDocsToc() {
  const [sections, setSections] = useState<TocSection[]>([])
  const [active, setActive] = useState("")

  useEffect(() => {
    const root = document.getElementById("docs-content")
    if (!root) return
    const heads = Array.from(
      root.querySelectorAll<HTMLElement>("h2[id], h3[id]")
    )

    const built: TocSection[] = []
    for (const h of heads) {
      if (h.tagName === "H2") {
        built.push({ id: h.id, title: h.textContent ?? "", items: [] })
      } else if (built.length) {
        built[built.length - 1].items.push({
          id: h.id,
          text: h.textContent ?? "",
        })
      }
    }

    const raf = requestAnimationFrame(() => {
      setSections(built)
      if (heads[0]) setActive(heads[0].id)
    })

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActive(visible[0].target.id)
      },
      { rootMargin: "-88px 0px -70% 0px", threshold: 0 }
    )
    heads.forEach((h) => observer.observe(h))
    return () => {
      cancelAnimationFrame(raf)
      observer.disconnect()
    }
  }, [])

  const activeSectionId =
    sections.find(
      (s) => s.id === active || s.items.some((i) => i.id === active)
    )?.id ?? sections[0]?.id

  return { sections, active, activeSectionId }
}
