"use client"

import { LogOut, User as UserIcon } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { createClient } from "@/lib/supabase/client"
import { cn } from "@/lib/utils"

/** Gravatar URL for an email (SHA-256, identicon fallback for unknown emails). */
async function gravatarUrl(email: string): Promise<string> {
  const normalized = email.trim().toLowerCase()
  const buf = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(normalized)
  )
  const hash = Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
  return `https://www.gravatar.com/avatar/${hash}?d=identicon&s=80`
}

export function UserMenu({ compact = false }: { compact?: boolean }) {
  const router = useRouter()
  const [email, setEmail] = useState<string | null>(null)
  const [avatar, setAvatar] = useState<string | null>(null)
  const [imgOk, setImgOk] = useState(true)

  useEffect(() => {
    createClient()
      .auth.getSession()
      .then(({ data }) => {
        const e = data.session?.user?.email ?? null
        setEmail(e)
        if (e) gravatarUrl(e).then(setAvatar)
      })
  }, [])

  async function handleSignOut() {
    await createClient().auth.signOut()
    router.push("/login")
    router.refresh()
  }

  const initial = email ? email[0]!.toUpperCase() : "?"

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className={cn(
            "flex items-center gap-2 rounded-md text-left transition-colors",
            compact
              ? ""
              : "w-full p-2 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
          )}
        >
          <span className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-sidebar-accent text-xs font-semibold ring-1 ring-border">
            {avatar && imgOk ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={avatar}
                alt=""
                className="size-full object-cover"
                onError={() => setImgOk(false)}
              />
            ) : (
              initial
            )}
          </span>
          {!compact && (
            <span className="min-w-0 flex-1 truncate text-sm font-medium">
              {email ?? "Account"}
            </span>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="truncate font-normal text-muted-foreground">
          {email ?? "Signed in"}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/settings/profile">
            <UserIcon className="size-4" /> Profile
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem variant="destructive" onClick={handleSignOut}>
          <LogOut className="size-4" /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
