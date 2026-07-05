"use client"

import {
  Camera,
  ChatCircleText,
  Check,
  Copy,
  Cube,
  Files,
  FolderSimple,
  SealCheck,
  SignOut,
} from "@phosphor-icons/react/dist/ssr"
import { useRouter } from "next/navigation"
import { useEffect, useRef, useState } from "react"
import { toast } from "@/lib/toast"
import useSWR from "swr"

import { SetPasswordForm } from "@/components/set-password-form"
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
import { LoaderOne } from "@/components/ui/loader"
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
    <div className="flex items-center gap-3 rounded-xl border bg-background p-4">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        {icon}
      </span>
      <div className="min-w-0">
        <div className="text-xl font-semibold tabular-nums leading-6">
          {value ?? "-"}
        </div>
        <div className="truncate text-xs text-muted-foreground">{label}</div>
      </div>
    </div>
  )
}

export default function ProfilePage() {
  const router = useRouter()
  const fileRef = useRef<HTMLInputElement>(null)

  const [email, setEmail] = useState<string | null>(null)
  const [name, setName] = useState("")
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null)
  const [gravatar, setGravatar] = useState<string | null>(null)
  const [meta, setMeta] = useState<AccountMeta | null>(null)
  const [savingName, setSavingName] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [copied, setCopied] = useState(false)
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
        setName((u.user_metadata?.username as string | undefined) ?? "")
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
    setSavingName(true)
    const { error } = await createClient().auth.updateUser({
      data: { username: name.trim() },
    })
    setSavingName(false)
    if (error) {
      toast.error(error.message)
      return
    }
    toast.success("Display name updated")
    router.refresh()
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

  async function handleSignOut(scope: "local" | "global") {
    const setter = scope === "global" ? setSigningOutAll : setSigningOut
    setter(true)
    const { error } = await createClient().auth.signOut({ scope })
    if (error) {
      toast.error(error.message)
      setter(false)
      return
    }
    router.push("/login")
    router.refresh()
  }

  async function handleDelete() {
    setDeleting(true)
    try {
      await api("/api/account", { method: "DELETE" })
      await createClient().auth.signOut()
      toast.success("Your account has been deleted")
      router.push("/signup")
      router.refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete account")
      setDeleting(false)
    }
  }

  const previewSrc = avatarUrl || gravatar

  return (
    // Fixed frame like every other page: the title never moves, the cards
    // scroll in their own container.
    <div className="flex h-[calc(100dvh-6.25rem)] flex-col gap-6 md:h-[calc(100dvh-4rem)]">
      <div className="shrink-0">
        <h1 className="text-2xl font-semibold">Profile</h1>
        <p className="text-sm text-muted-foreground">
          Manage your account, security, sessions and appearance.
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto pb-1">
        {/* Identity: avatar with hover-to-change, name, email, account meta. */}
        <Card>
          <CardContent className="flex flex-col gap-6 p-6 sm:flex-row sm:items-center">
            <div className="group relative shrink-0 self-center">
              <UserAvatar
                key={previewSrc ?? "none"}
                src={previewSrc}
                name={name || email}
                className="size-28 text-3xl"
              />
              <button
                type="button"
                aria-label="Change profile picture"
                disabled={uploading}
                onClick={() => fileRef.current?.click()}
                className="absolute inset-0 flex items-center justify-center rounded-full bg-black/50 text-white opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
              >
                {uploading ? <LoaderOne /> : <Camera className="size-6" />}
              </button>
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                hidden
                onChange={handleAvatarChange}
              />
            </div>

            <div className="min-w-0 flex-1 space-y-4">
              <div className="space-y-2">
                <Label htmlFor="display-name">Display name</Label>
                <div className="flex gap-2">
                  <Input
                    id="display-name"
                    value={name}
                    placeholder="Your name"
                    maxLength={50}
                    onChange={(e) => setName(e.target.value)}
                    className="max-w-72"
                  />
                  <Button onClick={handleSaveName} disabled={savingName}>
                    {savingName ? <LoaderOne /> : "Save"}
                  </Button>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">{email ?? "-"}</span>
                {meta?.verified ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                    <SealCheck className="size-3.5" weight="fill" />
                    Verified
                  </span>
                ) : null}
              </div>

              <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-muted-foreground">
                <span>Member since {formatDate(meta?.createdAt ?? null)}</span>
                <span>Last sign-in {formatDate(meta?.lastSignIn ?? null)}</span>
                <button
                  type="button"
                  onClick={handleCopyId}
                  title="Copy account ID (useful in support requests)"
                  className="inline-flex items-center gap-1 font-mono transition-colors hover:text-foreground"
                >
                  {copied ? (
                    <Check className="size-3.5 text-emerald-500" />
                  ) : (
                    <Copy className="size-3.5" />
                  )}
                  {meta ? `${meta.id.slice(0, 8)}…` : "-"}
                </button>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Account-wide usage at a glance. */}
        <Card>
          <CardHeader>
            <CardTitle>Usage overview</CardTitle>
            <CardDescription>
              Everything this account has indexed and served, across all
              projects.
            </CardDescription>
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

        <div className="grid items-start gap-6 lg:grid-cols-2">
          {/* Security */}
          <Card>
            <CardHeader>
              <CardTitle>Change password</CardTitle>
              <CardDescription>
                Min 12 characters, one uppercase, one special character.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SetPasswordForm
                submitLabel="Update password"
                onSuccess={() => toast.success("Password updated")}
              />
            </CardContent>
          </Card>

          <div className="space-y-6">
            {/* Sessions */}
            <Card>
              <CardHeader>
                <CardTitle>Sessions</CardTitle>
                <CardDescription>
                  Sign out here, or everywhere at once if a device was lost or
                  a session looks suspicious.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  disabled={signingOut || signingOutAll}
                  onClick={() => handleSignOut("local")}
                >
                  {signingOut ? (
                    <LoaderOne />
                  ) : (
                    <>
                      <SignOut className="size-4" />
                      Sign out
                    </>
                  )}
                </Button>
                <Button
                  variant="outline"
                  disabled={signingOut || signingOutAll}
                  onClick={() => handleSignOut("global")}
                >
                  {signingOutAll ? <LoaderOne /> : "Sign out of all devices"}
                </Button>
              </CardContent>
            </Card>

            {/* Appearance */}
            <Card>
              <CardHeader>
                <CardTitle>Appearance</CardTitle>
                <CardDescription>
                  Choose how Oreag looks on this device.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ThemeToggle />
              </CardContent>
            </Card>
          </div>
        </div>

        {/* Danger zone */}
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle className="text-destructive">Danger zone</CardTitle>
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
              {deleting ? <LoaderOne /> : "Delete forever"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
