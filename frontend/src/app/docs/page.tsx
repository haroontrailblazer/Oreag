import { ArrowSquareOutIcon as ArrowSquareOut} from "@phosphor-icons/react/dist/ssr"
import type { Metadata } from "next"
import Link from "next/link"

import { BrandMark } from "@/components/ui/brand-mark"

import sections from "./content.json"
import { DocsMobileNav } from "./docs-mobile-nav"
import { DocsOnThisPage } from "./docs-on-this-page"
import { DocsSidebar } from "./docs-sidebar"
import { Markdown } from "./markdown"

const DOCS_TITLE = "Documentation - Oreag"
const DOCS_DESCRIPTION =
  "Everything in Oreag: projects, uploading documents, the RAG query API, " +
  "agentic retrieval, agent memory, the memory graph, the MCP server, and API keys."

export const metadata: Metadata = {
  title: DOCS_TITLE,
  description: DOCS_DESCRIPTION,
  // openGraph has to be restated, not just `title`/`description`.
  //
  // Next.js merges metadata from the root layout, but a page's own title and
  // description do NOT flow into the inherited openGraph block - so this page
  // rendered <title>Documentation - Oreag</title> while sharing to LinkedIn and
  // WhatsApp as "Oreag - RAG & Memory as a Service". The image and siteName
  // still come from the root, which is the intent: one brand card, per-page
  // words.
  openGraph: {
    title: DOCS_TITLE,
    description: DOCS_DESCRIPTION,
    url: "/docs",
  },
  twitter: {
    title: DOCS_TITLE,
    description: DOCS_DESCRIPTION,
  },
}

export default function DocsPage() {
  return (
    <div className="min-h-dvh bg-background">
      <header className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-10">
          <div className="flex min-w-0 items-center gap-2">
            <DocsMobileNav />
            <Link href="/" className="flex min-w-0 items-center gap-2.5">
              <BrandMark
                className="size-8 shrink-0 rounded-lg"
                imgClassName="scale-150"
              />
              <span className="truncate font-semibold tracking-tight">
                Oreag{" "}
                <span className="font-normal text-muted-foreground">docs</span>
              </span>
            </Link>
          </div>
          <Link
            href="/dashboard"
            className="inline-flex shrink-0 items-center gap-1 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Dashboard
            <ArrowSquareOut className="size-4" />
          </Link>
        </div>
      </header>

      <div className="mx-auto flex max-w-[1600px] gap-8 px-4 sm:px-6 lg:px-8">
        <aside className="sticky top-14 hidden h-[calc(100dvh-3.5rem)] w-52 shrink-0 overflow-y-auto py-8 lg:block">
          <DocsSidebar />
        </aside>

        <main
          id="docs-content"
          className="min-w-0 flex-1 space-y-16 py-10 pb-24"
        >
          {sections.map((s) => (
            <section key={s.id}>
              <Markdown sectionId={s.id}>{s.body}</Markdown>
            </section>
          ))}
        </main>

        <aside className="sticky top-14 hidden h-[calc(100dvh-3.5rem)] w-48 shrink-0 overflow-y-auto py-10 lg:block">
          <DocsOnThisPage />
        </aside>
      </div>
    </div>
  )
}
