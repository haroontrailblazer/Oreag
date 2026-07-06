"use client"

import { Lightbulb } from "@phosphor-icons/react/dist/ssr"
import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { cn } from "@/lib/utils"

export interface BestPracticeTip {
  title: string
  detail: string
}

/**
 * A compact "Best practices" pill for a page or tab. Tips open in a floating
 * popover, so it never adds page height - fixed-viewport layouts stay fixed.
 * Long tip lists scroll INSIDE the popover, never the page. `children` lets a
 * page append custom sections (e.g. the Visualize dimension explainer).
 */
export function BestPractices({
  title = "Best practices",
  tips,
  children,
  className,
}: {
  title?: string
  tips: BestPracticeTip[]
  children?: ReactNode
  className?: string
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          aria-label="Best practices"
          title="Best practices"
          className={cn(
            // Icon-only on phones so it doesn't crowd the page title/actions;
            // full label from sm+.
            "size-7 shrink-0 rounded-full p-0 text-muted-foreground hover:text-foreground sm:h-7 sm:w-auto sm:gap-1.5 sm:px-2.5 sm:text-xs sm:font-medium",
            className
          )}
        >
          <Lightbulb className="size-3.5" />
          <span className="hidden sm:inline">Best practices</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="border-b px-4 py-2.5 text-sm font-semibold">{title}</div>
        <div className="styled-scrollbar max-h-80 space-y-3 overflow-y-auto px-4 py-3">
          {tips.map((tip) => (
            <div key={tip.title} className="space-y-0.5">
              <p className="text-xs font-medium">{tip.title}</p>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {tip.detail}
              </p>
            </div>
          ))}
          {children}
        </div>
      </PopoverContent>
    </Popover>
  )
}
