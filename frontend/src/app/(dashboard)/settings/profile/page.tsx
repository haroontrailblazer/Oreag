"use client"

import {
  CameraIcon as Camera,
  ArrowUpRightIcon as ArrowUpRight,
  ChatCircleTextIcon as ChatCircleText,
  CheckIcon as Check,
  CopyIcon as Copy,
  CubeIcon as Cube,
  FilesIcon as Files,
  FolderSimpleIcon as FolderSimple,
  PencilSimpleIcon as PencilSimple,
  SealCheckIcon as SealCheck,
  SignOutIcon as SignOut,
  ShieldCheckIcon as ShieldCheck,
  WarningCircleIcon as WarningCircle,
} from "@phosphor-icons/react/dist/ssr"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useRef, useState } from "react"
import { toast } from "@/lib/toast"
import useSWR from "swr"

import { ChangePasswordCard } from "@/components/settings/change-password-card"
import { TwoFactorCard } from "@/components/settings/two-factor-card"
import { ThemeToggle } from "@/components/theme-toggle"
import { UserAvatar } from "@/components/user-avatar"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Spin } from "@/components/ui/loader"
import { api, fetcher } from "@/lib/api"
import { gravatarUrl } from "@/lib/avatar"
import { createClient } from "@/lib/supabase/client"
import type { Project } from "@/lib/types"

const MAX_AVATAR_BYTES = 3 * 1024 * 1024

type AccountMeta = {
  id: string
  createdAt: string | null
  lastSignIn: string | null
  verified: boolean
}

function formatDate(value: string | null): string {
  if (!value) return "-"
  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

function StatTile({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: number | null
}) {
  return (
    <div className="flex min-w-0 flex-col gap-3 rounded-xl border bg-background p-4 sm:flex-row sm:items-center">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        {icon}
      </span>
      <div className="min-w-0">
        <div className="break-all text-2xl font-semibold tabular-nums leading-8 tracking-tight">
          {value == null ? <span aria-label="Not available">—</span> : value.toLocaleString("en-US")}
        </div>
        <div className="text-xs leading-relaxed text-muted-foreground">{label}</div>
      </div>
    </div>
  )
}

export default function ProfilePage() {
  const router = useRouter()
  const fileRef = useRef<HTMLInputElement>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)

  const [email, setEmail] = useState<string | null>(null)
  const [name, setName] = useState("")
  const [savedName, setSavedName] = useState("")
  const [editingName, setEditingName] = useState(false)
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null)
  const [gravatar, setGravatar] = useState<string | null>(null)
  const [meta, setMeta] = useState<AccountMeta | null>(null)
  const [savingName, setSavingName] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [resending, setResending] = useState(false)
  const [signingOut, setSigningOut] = useState(false)
  const [signingOutAll, setSigningOutAll] = useState(false)

  const [confirmOpen, setConfirmOpen] = useState(false)
  const [confirmText, setConfirmText] = useState("")
  const [deleting, setDeleting] = useState(false)

  // Account-wide usage, summed from the same list the dashboard shows.
  const { data: projects } = useSWR<Project[]>("/api/projects", fetcher)
  const totals = projects
    ? {
        projects: projects.length,
        files: projects.reduce((n, p) => n + p.file_count, 0),
        chunks: projects.reduce((n, p) => n + p.chunk_count, 0),
        queries: projects.reduce((n, p) => n + p.query_count, 0),
      }
    : null

  useEffect(() => {
    createClient()
      .auth.getSession()
      .then(({ data }) => {
        const u = data.session?.user
        if (!u) return
        const e = u.email ?? null
        setEmail(e)
        const displayName =
          (u.user_metadata?.username as string | undefined) ?? ""
        setName(displayName)
        setSavedName(displayName)
        const a = (u.user_metadata?.avatar_url as string | undefined) ?? null
        setAvatarUrl(a)
        if (!a && e) gravatarUrl(e).then(setGravatar)
        setMeta({
          id: u.id,
          createdAt: u.created_at ?? null,
          lastSignIn: u.last_sign_in_at ?? null,
          verified: Boolean(u.email_confirmed_at),
        })
      })
  }, [])

  async function handleSaveName() {
    const nextName = name.trim()
    setSavingName(true)
    const { error } = await createClient().auth.updateUser({
      data: { username: nextName },
    })
    setSavingName(false)
    if (error) {
      toast.error(error.message)
      return
    }
    setName(nextName)
    setSavedName(nextName)
    setEditingName(false)
    toast.success("Display name updated")
    router.refresh()
  }

  function handleEditName() {
    setEditingName(true)
    requestAnimationFrame(() => {
      nameInputRef.current?.focus()
      nameInputRef.current?.select()
    })
  }

  async function handleAvatarChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (fileRef.current) fileRef.current.value = ""
    if (!file) return
    if (!file.type.startsWith("image/")) {
      toast.error("Please choose an image file")
      return
    }
    if (file.size > MAX_AVATAR_BYTES) {
      toast.error("Image must be under 3 MB")
      return
    }
    setUploading(true)
    try {
      const supabase = createClient()
      const {
        data: { user },
      } = await supabase.auth.getUser()
      if (!user) throw new Error("Not signed in")
      const ext = file.name.split(".").pop()?.toLowerCase() || "png"
      const path = `${user.id}/avatar.${ext}`
      const { error: upErr } = await supabase.storage
        .from("avatars")
        .upload(path, file, { upsert: true, contentType: file.type })
      if (upErr) throw upErr
      const publicUrl =
        supabase.storage.from("avatars").getPublicUrl(path).data.publicUrl +
        `?v=${Date.now()}`
      const { error: updErr } = await supabase.auth.updateUser({
        data: { avatar_url: publicUrl },
      })
      if (updErr) throw updErr
      setAvatarUrl(publicUrl)
      toast.success("Profile picture updated")
      router.refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed")
    } finally {
      setUploading(false)
    }
  }

  function handleCopyId() {
    if (!meta) return
    navigator.clipboard.writeText(meta.id).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  async function handleResendVerification() {
    if (!email) return
    setResending(true)
    const { error } = await createClient().auth.resend({
      type: "signup",
      email,
    })
    setResending(false)
    if (error) {
      toast.error(error.message)
      return
    }
    toast.success("Verification email sent - check your inbox (and spam).")
  }

  async function handleSignOut(scope: "local" | "global") {
    const setter = scope === "global" ? setSigningOutAll : setSigningOut
    setter(true)
    const { error } = await createClient().auth.signOut({ scope })
    if (error) {
      toast.error(error.message)
      setter(false)
      return
    }
    // Hard navigation - SWR's cache and preload map are module-level and would
    // otherwise survive into the next account signed in to this tab. See
    // components/user-menu.tsx for the full reasoning.
    window.location.replace("/login")
  }

  async function handleDelete() {
    setDeleting(true)
    try {
      await api("/api/account", { method: "DELETE" })
      await createClient().auth.signOut()
      toast.success("Your account has been deleted")
      // Hard navigation for the same reason, and more urgently here: every
      // cached row belongs to an account that no longer exists.
      window.location.replace("/signup")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete account")
      setDeleting(false)
    }
  }

  const previewSrc = avatarUrl || gravatar

  return (
    // Desktop: a fixed frame - the title stays put and the cards scroll in
    // their own region (md:h-full + md:overflow-hidden). Mobile: NO fixed
    // frame - the page flows and scrolls naturally with the layout's min-h-dvh,
    // so there's no leftover black band below a mis-sized frame. overflow-x
    // guards against any stray horizontal scroll.
    <div className="flex flex-col gap-6 overflow-x-hidden md:h-full md:min-h-0 md:overflow-hidden">
      <div className="shrink-0 space-y-1 border-b pb-5">
        <h1 className="text-2xl font-semibold tracking-tight">Profile</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Manage your account, security, sessions and appearance.
        </p>
      </div>

      <div className="space-y-6 md:min-h-0 md:flex-1 md:overflow-y-auto md:pb-4 md:pr-1">
        {/* Identity hero: avatar and account details side by side, full width. */}
        <Card className="gap-0 overflow-hidden py-0">
          <CardHeader className="border-b bg-muted/20 py-5">
            <CardTitle>Personal details</CardTitle>
            <CardDescription>Your name and photo across your Oreag workspace.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-6 p-5 sm:flex-row sm:items-start sm:gap-8 sm:p-6">
            <div className="flex shrink-0 items-center gap-4 sm:flex-col sm:items-center sm:text-center">
              <div className="relative shrink-0">
                <UserAvatar
                  key={previewSrc ?? "none"}
                  src={previewSrc}
                  name={savedName || email}
                  className="size-20 text-3xl sm:size-24"
                />
                <button
                  type="button"
                  aria-label="Change profile picture"
                  disabled={uploading}
                  onClick={() => fileRef.current?.click()}
                  className="absolute -bottom-1 -right-1 flex size-9 items-center justify-center rounded-full border bg-background text-foreground shadow-sm transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-wait"
                >
                  {uploading ? <Spin /> : <Camera className="size-4" />}
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  hidden
                  onChange={handleAvatarChange}
                />
              </div>
              <div className="space-y-1.5">
                <Button type="button" variant="outline" size="sm" disabled={uploading} onClick={() => fileRef.current?.click()}>
                  {uploading ? "Uploading…" : "Change photo"}
                </Button>
                <p className="text-xs text-muted-foreground">Image up to 3 MB</p>
              </div>
            </div>

            <div className="min-w-0 flex-1 space-y-4">
              <div className="space-y-1">
                <h2 className="break-words text-xl font-semibold tracking-tight">{savedName || "Your profile"}</h2>
                <p className="text-xs text-muted-foreground">Keep your account details up to date.</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="display-name">Display name</Label>
                <div className="flex items-center gap-2">
                  <Input
                    ref={nameInputRef}
                    id="display-name"
                    value={name}
                    placeholder="Your name"
                    maxLength={50}
                    autoComplete="nickname"
                    aria-describedby="display-name-hint"
                    readOnly={!editingName}
                    disabled={savingName}
                    onChange={(e) => setName(e.target.value)}
                    onKeyDown={(e) => {
                      if (
                        e.key === "Enter" &&
                        editingName &&
                        !savingName &&
                        name.trim() !== savedName
                      ) {
                        handleSaveName()
                      }
                      if (e.key === "Escape" && !savingName) {
                        setName(savedName)
                        setEditingName(false)
                      }
                    }}
                    className="min-w-0 max-w-md read-only:cursor-default read-only:bg-muted/30"
                  />
                  {editingName ? (
                    <Button
                      className="shrink-0"
                      onClick={handleSaveName}
                      disabled={savingName || name.trim() === savedName}
                    >
                      {savingName ? <><Spin /><span className="sr-only">Saving name</span></> : "Save"}
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      onClick={handleEditName}
                      aria-label="Edit display name"
                      title="Edit display name"
                    >
                      <PencilSimple className="size-4" />
                    </Button>
                  )}
                </div>
                <div className="flex max-w-md items-center justify-between gap-3">
                  <p id="display-name-hint" className="text-xs text-muted-foreground">{editingName ? `${name.length}/50 characters` : "Choose the name shown in your workspace."}</p>
                  {editingName && (
                    <Button type="button" variant="ghost" size="sm" disabled={savingName} onClick={() => { setName(savedName); setEditingName(false) }}>
                      Cancel
                    </Button>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-medium">Email address</p>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="min-w-0 break-all text-muted-foreground">{email ?? "Loading account…"}</span>
                {meta?.verified ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                    <SealCheck className="size-3.5" weight="fill" />
                    Verified
                  </span>
                ) : meta ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-600 dark:text-amber-400">
                    <WarningCircle className="size-3.5" weight="fill" />
                    Unverified
                  </span>
                ) : null}
              </div>
              </div>

              {/* Verify prompt: only when the email isn't confirmed yet. */}
              {meta && !meta.verified ? (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-left text-xs text-amber-900 dark:border-amber-800/50 dark:bg-amber-950/40 dark:text-amber-200">
                  <span className="min-w-0 flex-1">
                    Your email isn&apos;t verified yet. Confirm it to secure your
                    account and keep access if you ever need to reset your
                    password.
                  </span>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 shrink-0 border-amber-400/60 bg-transparent"
                    disabled={resending}
                    onClick={handleResendVerification}
                  >
                    {resending ? <Spin /> : "Resend email"}
                  </Button>
                </div>
              ) : null}

            </div>
          </CardContent>
          <dl className="grid gap-4 border-t bg-muted/20 px-5 py-4 text-sm sm:grid-cols-3 sm:px-6">
            <div className="space-y-1">
              <dt className="text-xs text-muted-foreground">Member since</dt>
              <dd className="font-medium">{formatDate(meta?.createdAt ?? null)}</dd>
            </div>
            <div className="space-y-1">
              <dt className="text-xs text-muted-foreground">Last sign-in</dt>
              <dd className="font-medium">{formatDate(meta?.lastSignIn ?? null)}</dd>
            </div>
            <div className="space-y-1">
              <dt className="text-xs text-muted-foreground">Account ID</dt>
              <dd>
                <button
                  type="button"
                  onClick={handleCopyId}
                  disabled={!meta}
                  aria-label={copied ? "Account ID copied" : "Copy account ID"}
                  title="Copy account ID (useful in support requests)"
                  className="inline-flex min-h-6 items-center gap-2 rounded font-mono text-xs transition-colors hover:text-muted-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50"
                >
                  {copied ? (
                    <Check className="size-3.5 text-emerald-500" />
                  ) : (
                    <Copy className="size-3.5" />
                  )}
                  <span aria-live="polite">{copied ? "Copied" : meta ? `${meta.id.slice(0, 8)}…` : "-"}</span>
                </button>
              </dd>
            </div>
          </dl>
        </Card>

        {/* Account-wide usage: full-width row of stat tiles. */}
        <Card>
          <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-1.5">
            <CardTitle>Workspace activity</CardTitle>
            <CardDescription>
              Everything this account has indexed and served, across all
              projects.
            </CardDescription>
            </div>
            <Button asChild variant="outline" size="sm" className="w-fit shrink-0">
              <Link href="/settings/usage">View usage <ArrowUpRight className="size-3.5" /></Link>
            </Button>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              icon={<FolderSimple className="size-4.5" />}
              label="Projects"
              value={totals?.projects ?? null}
            />
            <StatTile
              icon={<Files className="size-4.5" />}
              label="Files indexed"
              value={totals?.files ?? null}
            />
            <StatTile
              icon={<Cube className="size-4.5" />}
              label="Chunks embedded"
              value={totals?.chunks ?? null}
            />
            <StatTile
              icon={<ChatCircleText className="size-4.5" />}
              label="Queries answered"
              value={totals?.queries ?? null}
            />
          </CardContent>
        </Card>

        <Card>
          <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1.5">
              <CardTitle>Appearance</CardTitle>
              <CardDescription>Choose a theme, or follow your device settings.</CardDescription>
            </div>
            <div className="w-full shrink-0 sm:w-64">
              <ThemeToggle showLabels />
            </div>
          </CardContent>
        </Card>

        <section aria-labelledby="profile-security-heading" className="space-y-4">
          <div className="flex items-start gap-3 pt-2">
            <ShieldCheck className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
            <div className="space-y-1">
              <h2 id="profile-security-heading" className="text-base font-semibold">Security &amp; access</h2>
              <p className="text-sm text-muted-foreground">Manage how you sign in and where you stay signed in.</p>
            </div>
          </div>
        {/* Full width: this is the most consequential security control on the
            page, and its factor lists need the room. */}
        <TwoFactorCard />

        <div className="grid items-start gap-4 lg:grid-cols-2">
          {/* Security - reauthentication-gated, see the card's own notes. */}
          <ChangePasswordCard />

          {/* Sessions */}
          <Card>
            <CardHeader>
              <CardTitle>Sessions</CardTitle>
              <CardDescription>
                Sign out here, or everywhere at once if a device was lost or a
                session looks suspicious.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="space-y-1">
                  <p className="text-sm font-medium">This device</p>
                  <p className="text-xs text-muted-foreground">End your current session.</p>
                </div>
              <Button
                variant="outline"
                disabled={signingOut || signingOutAll}
                onClick={() => handleSignOut("local")}
              >
                {signingOut ? (
                  <Spin />
                ) : (
                  <>
                    <SignOut className="size-4" />
                    Sign out
                  </>
                )}
              </Button>
              </div>
              <div className="space-y-3 border-t pt-4">
                <div className="space-y-1">
                  <p className="text-sm font-medium">All devices</p>
                  <p className="text-xs leading-relaxed text-muted-foreground">Sign out across devices, including this one.</p>
                </div>
              <Button
                variant="outline"
                disabled={signingOut || signingOutAll}
                onClick={() => handleSignOut("global")}
              >
                {signingOutAll ? <Spin /> : "Sign out of all devices"}
              </Button>
              </div>
            </CardContent>
          </Card>
        </div>
        </section>

          {/* Danger zone */}
          <Card className="border-destructive/40 bg-destructive/[0.02]">
            <CardHeader className="gap-2">
              <CardTitle className="text-destructive">Delete account</CardTitle>
              <CardDescription>
                Permanently delete your account and all of your projects, files,
                indexed chunks, API keys and provider keys. This cannot be
                undone.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="destructive" onClick={() => setConfirmOpen(true)}>
                Delete my account
              </Button>
            </CardContent>
          </Card>
      </div>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete your account?</DialogTitle>
            <DialogDescription>
              This permanently removes your account and every project, file, key
              and log tied to it. Type <strong>DELETE</strong> to confirm.
            </DialogDescription>
          </DialogHeader>
          <Input
            id="delete-account-confirmation"
            aria-label="Type DELETE to confirm account deletion"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="DELETE"
            autoComplete="off"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={confirmText !== "DELETE" || deleting}
              onClick={handleDelete}
            >
              {deleting ? <Spin /> : "Delete forever"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
