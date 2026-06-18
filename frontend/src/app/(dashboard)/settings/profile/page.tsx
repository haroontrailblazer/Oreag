"use client"

import { useRouter } from "next/navigation"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

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
import { gravatarUrl } from "@/lib/avatar"
import { api } from "@/lib/api"
import { createClient } from "@/lib/supabase/client"

const MAX_AVATAR_BYTES = 3 * 1024 * 1024

export default function ProfilePage() {
  const router = useRouter()
  const fileRef = useRef<HTMLInputElement>(null)

  const [email, setEmail] = useState<string | null>(null)
  const [name, setName] = useState("")
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null)
  const [gravatar, setGravatar] = useState<string | null>(null)
  const [savingName, setSavingName] = useState(false)
  const [uploading, setUploading] = useState(false)

  const [confirmOpen, setConfirmOpen] = useState(false)
  const [confirmText, setConfirmText] = useState("")
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    createClient()
      .auth.getSession()
      .then(({ data }) => {
        const u = data.session?.user
        const e = u?.email ?? null
        setEmail(e)
        setName((u?.user_metadata?.username as string | undefined) ?? "")
        const a = (u?.user_metadata?.avatar_url as string | undefined) ?? null
        setAvatarUrl(a)
        if (!a && e) gravatarUrl(e).then(setGravatar)
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
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Profile</h1>
        <p className="text-sm text-muted-foreground">Manage your account.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>
            Your display name and picture appear across the dashboard.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex items-center gap-4">
            <UserAvatar
              key={previewSrc ?? "none"}
              src={previewSrc}
              name={name || email}
              className="size-16 text-xl"
            />
            <div className="space-y-1">
              <Button
                variant="outline"
                size="sm"
                disabled={uploading}
                onClick={() => fileRef.current?.click()}
              >
                {uploading ? "Uploading…" : "Change picture"}
              </Button>
              <p className="text-xs text-muted-foreground">
                JPG, PNG or GIF, up to 3&nbsp;MB.
              </p>
            </div>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              hidden
              onChange={handleAvatarChange}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="display-name">Display name</Label>
            <div className="flex gap-2">
              <Input
                id="display-name"
                value={name}
                placeholder="Your name"
                maxLength={50}
                onChange={(e) => setName(e.target.value)}
              />
              <Button onClick={handleSaveName} disabled={savingName}>
                {savingName ? "Saving…" : "Save"}
              </Button>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="profile-email">Email</Label>
            <Input id="profile-email" value={email ?? ""} readOnly disabled />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Appearance</CardTitle>
          <CardDescription>Choose how Oreag looks on this device.</CardDescription>
        </CardHeader>
        <CardContent>
          <ThemeToggle />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Change password</CardTitle>
          <CardDescription>
            Set a new password (min 12 characters, one uppercase, one special
            character).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SetPasswordForm
            submitLabel="Update password"
            onSuccess={() => toast.success("Password updated")}
          />
        </CardContent>
      </Card>

      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="text-destructive">Danger zone</CardTitle>
          <CardDescription>
            Permanently delete your account and all of your projects, files,
            indexed chunks, API keys and provider keys. This cannot be undone.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" onClick={() => setConfirmOpen(true)}>
            Delete my account
          </Button>
        </CardContent>
      </Card>

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
              {deleting ? "Deleting…" : "Delete forever"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
