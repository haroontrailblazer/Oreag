"use client"

import { List } from "@phosphor-icons/react/dist/ssr"
import { useState } from "react"

import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"

import { DocsSidebar } from "./docs-sidebar"

/**
 * Mobile section navigation for the docs: a hamburger button (shown below the
 * lg breakpoint, where the fixed left rail is hidden) that opens the topic list
 * in a left drawer. Tapping any topic navigates to it and closes the drawer.
 */
export function DocsMobileNav() {
  const [open, setOpen] = useState(false)
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        aria-label="Open documentation menu"
        className="inline-flex size-9 shrink-0 items-center justify-center rounded-md border text-muted-foreground transition-colors hover:text-foreground lg:hidden"
      >
        <List className="size-4" />
      </SheetTrigger>
      <SheetContent side="left" className="w-72 p-4">
        <SheetTitle className="sr-only">Documentation</SheetTitle>
        {/* Any topic link click bubbles here and closes the drawer. */}
        <div className="mt-2 overflow-y-auto" onClick={() => setOpen(false)}>
          <DocsSidebar />
        </div>
      </SheetContent>
    </Sheet>
  )
}
