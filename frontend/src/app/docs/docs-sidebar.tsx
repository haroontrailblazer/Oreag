"use client"

import { useDocsToc } from "./use-docs-toc"

/**
 * Left navigation: a flat list of the documentation topics. The topic you're
 * currently scrolled into is highlighted (scroll-spy). Sub-topics are NOT shown
 * here — they live in the right-hand "On this page" panel so the left rail stays
 * a clean, scannable topic list.
 */
export function DocsSidebar() {
  const { sections, activeSectionId } = useDocsToc()

  return (
    <nav className="space-y-0.5 text-sm">
      <p className="px-3 pb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        Documentation
      </p>
      {sections.map((section) => (
        <a
          key={section.id}
          href={`#${section.id}`}
          className={
            "block truncate rounded-md px-3 py-1.5 transition-colors " +
            (activeSectionId === section.id
              ? "bg-muted font-medium text-foreground"
              : "text-muted-foreground hover:text-foreground")
          }
        >
          {section.title}
        </a>
      ))}
    </nav>
  )
}
