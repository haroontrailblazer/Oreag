import Link from "next/link"

import { BrandMark } from "@/components/ui/brand-mark"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card"
import { cn } from "@/lib/utils"

const tab =
  "rounded-md py-2 text-center text-sm font-medium transition-colors"
const tabActive = "bg-card text-foreground shadow-sm"
const tabIdle = "text-muted-foreground hover:text-foreground"

/** Shared chrome for the auth screens: brand header + Login/Sign Up toggle. */
export function AuthShell({
  active,
  children,
}: {
  active?: "login" | "signup"
  children: React.ReactNode
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-md py-8">
        <CardHeader className="justify-items-center gap-3 text-center">
          <BrandMark
            className="size-14 rounded-2xl"
            imgClassName="scale-150"
          />
          <CardDescription>
            Build and query RAG APIs over your documents
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {active && (
            <div className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1">
              <Link
                href="/login"
                className={cn(tab, active === "login" ? tabActive : tabIdle)}
              >
                Login
              </Link>
              <Link
                href="/signup"
                className={cn(tab, active === "signup" ? tabActive : tabIdle)}
              >
                Sign Up
              </Link>
            </div>
          )}
          {children}
        </CardContent>
      </Card>
    </div>
  )
}
