"use client"

import { useEffect, useState } from "react"
import { FunnelIcon } from "@phosphor-icons/react/dist/ssr"
import { Button } from "@/components/ui/button"
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"

/** The same controlled filters as desktop, shown on demand below md. */
export function MobileFilters({ title, activeCount, onReset, children }: {
  title: string
  activeCount: number
  onReset: () => void
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 768px)")
    function onResize() { if (desktop.matches) setOpen(false) }
    desktop.addEventListener("change", onResize)
    return () => desktop.removeEventListener("change", onResize)
  }, [])

  return <Dialog open={open} onOpenChange={setOpen}>
    <DialogTrigger asChild>
      <Button variant="outline" size="icon" className="relative size-9 shrink-0 md:hidden" aria-label={activeCount ? `Filters (${activeCount} active)` : "Filters"}>
        <FunnelIcon aria-hidden="true" className="size-4" />
        {activeCount > 0 && <span aria-hidden="true" className="absolute -right-1 -top-1 flex size-4 items-center justify-center rounded-full bg-foreground text-[10px] font-semibold text-background">{activeCount}</span>}
      </Button>
    </DialogTrigger>
    <DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col gap-4 p-5">
      <DialogHeader className="shrink-0 pr-6 text-left">
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>Choose filters, then close to view your results.</DialogDescription>
      </DialogHeader>
      <div className="min-h-0 overflow-y-auto">{children}</div>
      <div className="flex shrink-0 items-center justify-between gap-3 border-t pt-4">
        <Button variant="ghost" size="sm" onClick={onReset}>Reset filters</Button>
        <DialogClose asChild><Button size="sm">Show results</Button></DialogClose>
      </div>
    </DialogContent>
  </Dialog>
}
