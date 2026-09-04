"use client"

import * as React from "react"
import { Switch as SwitchPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

/**
 * An on/off toggle.
 *
 * Reach for this over a checkbox when the control takes effect immediately, or
 * reads as a mode the thing is IN rather than an item being selected. A
 * checkbox says "include this when I save"; a switch says "this is on".
 *
 * Radix renders a real `role="switch"` button with `aria-checked`, so keyboard
 * and screen-reader behaviour come for free - which a div with an onClick does
 * not. Same `radix-ui` package every other primitive here uses; no new
 * dependency.
 */
function Switch({
  className,
  ...props
}: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "peer inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-transparent",
        "transition-colors outline-none",
        "focus-visible:ring-[3px] focus-visible:ring-ring/50",
        "disabled:cursor-not-allowed disabled:opacity-50",
        // The track carries the state: filled when on, a recessed well when
        // off, so it reads at a glance without relying on the knob position.
        "data-[state=checked]:bg-foreground data-[state=unchecked]:bg-input",
        "dark:data-[state=unchecked]:bg-input/60",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className={cn(
          "pointer-events-none block size-4 rounded-full bg-background shadow-sm ring-0",
          "transition-transform",
          "data-[state=checked]:translate-x-[calc(100%-2px)] data-[state=unchecked]:translate-x-0.5"
        )}
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
