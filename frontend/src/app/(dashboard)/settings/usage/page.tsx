import { UsageDashboard } from "@/components/settings/usage-dashboard"

export default function UsagePage() {
  // Heading + range selector live inside the client component (they share a
  // row), which also owns the fixed-frame layout like the sibling pages.
  return <UsageDashboard />
}
