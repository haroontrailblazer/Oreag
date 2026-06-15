"use client"

import { Laptop, Moon, Sun } from "lucide-react"
import { useTheme } from "next-themes"
import { useSyncExternalStore } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const OPTIONS = [
  { value: "system", label: "System", icon: Laptop },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
]

function subscribe(onStoreChange: () => void) {
  queueMicrotask(onStoreChange)
  return () => {}
}

function getClientSnapshot() {
  return true
}

function getServerSnapshot() {
  return false
}

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const mounted = useSyncExternalStore(
    subscribe,
    getClientSnapshot,
    getServerSnapshot
  )
  const currentTheme = theme ?? "system"

  if (!mounted) {
    return (
      <div className="grid grid-cols-3 gap-1 rounded-lg border bg-background p-1">
        {OPTIONS.map(({ label, icon: Icon }) => (
          <div
            key={label}
            className="inline-flex h-7 items-center justify-center rounded-md px-2 text-muted-foreground"
          >
            <Icon className="size-3.5" />
            <span className="sr-only">{label}</span>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-3 gap-1 rounded-lg border bg-background p-1">
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const selected = currentTheme === value

        return (
          <Button
            key={value}
            type="button"
            variant="ghost"
            size="sm"
            title={label}
            aria-label={`${label} theme`}
            aria-pressed={selected}
            onClick={() => setTheme(value)}
            className={cn(
              "h-7 px-2 text-xs text-muted-foreground",
              selected && "bg-accent text-accent-foreground shadow-xs"
            )}
          >
            <Icon className="size-3.5" />
            <span className="sr-only">{label}</span>
          </Button>
        )
      })}
    </div>
  )
}
