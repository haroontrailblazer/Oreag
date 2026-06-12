import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const STYLES: Record<string, string> = {
  empty: "bg-muted text-muted-foreground",
  pending: "bg-amber-100 text-amber-800",
  processing: "bg-amber-100 text-amber-800 animate-pulse",
  indexing: "bg-amber-100 text-amber-800 animate-pulse",
  indexed: "bg-emerald-100 text-emerald-800",
  ready: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
  error: "bg-red-100 text-red-800",
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="secondary" className={cn("capitalize", STYLES[status])}>
      {status}
    </Badge>
  )
}
