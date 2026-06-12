"use client"

import { Laptop, Moon, Sun } from "lucide-react"
import { useTheme } from "next-themes"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const OPTIONS = [
  { value: "system", label: "System", icon: Laptop },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
]

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const currentTheme = theme ?? "system"

  return (
    <div
      suppressHydrationWarning
      className="grid grid-cols-3 gap-1 rounded-lg border bg-background p-1"
    >
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
