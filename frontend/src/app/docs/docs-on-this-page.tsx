"use client"

import { useDocsToc } from "./use-docs-toc"

/**
 * Right rail: the sub-topics of the topic you're currently reading, with the
 * active one highlighted (scroll-spy). Mirrors the left nav's active state.
 */
export function DocsOnThisPage() {
  const { sections, active, activeSectionId } = useDocsToc()
  const section = sections.find((s) => s.id === activeSectionId)
  if (!section || section.items.length === 0) return null

  return (
    <nav className="text-sm">
      <p className="mb-2 px-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        On this page
      </p>
      <ul className="border-l">
        {section.items.map((item) => (
          <li key={item.id}>
            <a
              href={`#${item.id}`}
              className={
                "-ml-px block border-l-2 py-1 pl-3 transition-colors " +
                (active === item.id
                  ? "border-foreground font-medium text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground")
              }
            >
              {item.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}
