"use client"

import { SignOut as LogOut, User as UserIcon } from "@phosphor-icons/react/dist/ssr"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"

import { UserAvatar } from "@/components/user-avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { gravatarUrl } from "@/lib/avatar"
import { createClient } from "@/lib/supabase/client"
import { cn } from "@/lib/utils"

export function UserMenu({ compact = false }: { compact?: boolean }) {
  const router = useRouter()
  const [email, setEmail] = useState<string | null>(null)
  const [name, setName] = useState<string | null>(null)
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null)
  const [gravatar, setGravatar] = useState<string | null>(null)

  useEffect(() => {
    const supabase = createClient()
    const load = () => {
      supabase.auth.getSession().then(({ data }) => {
        const u = data.session?.user
        const e = u?.email ?? null
        setEmail(e)
        setName((u?.user_metadata?.username as string | undefined) ?? null)
        const a = (u?.user_metadata?.avatar_url as string | undefined) ?? null
        setAvatarUrl(a)
        if (!a && e) gravatarUrl(e, 80).then(setGravatar)
      })
    }
    load()
    // re-read on sign-in / profile (USER_UPDATED) changes so the sidebar stays live
    const { data: sub } = supabase.auth.onAuthStateChange(() => load())
    return () => sub.subscription.unsubscribe()
  }, [])

  async function handleSignOut() {
    await createClient().auth.signOut()
    router.push("/login")
    router.refresh()
  }

  const displayName = name || email?.split("@")[0] || "Account"
  const src = avatarUrl || gravatar

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
          <UserAvatar
            key={src ?? "none"}
            src={src}
            name={displayName}
            className="size-8 text-xs"
          />
          {!compact && (
            <span className="min-w-0 flex-1 truncate text-sm font-medium">
              {displayName}
            </span>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="font-normal">
          <div className="truncate font-medium">{displayName}</div>
          {email && (
            <div className="truncate text-xs text-muted-foreground">{email}</div>
          )}
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
