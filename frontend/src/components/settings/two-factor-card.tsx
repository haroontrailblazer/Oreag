"use client"

import {
  DeviceMobile,
  Fingerprint,
  Key,
  ShieldCheck,
  Trash,
  Warning,
} from "@phosphor-icons/react/dist/ssr"
import Image from "next/image"
import { useCallback, useState } from "react"
import useSWR from "swr"

import {
  OtpField,
  TOTP_LENGTH,
  isCompleteCode,
} from "@/components/auth/otp-field"
import { Badge } from "@/components/ui/badge"
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
import { authErrorMessage, isPasskeyCancellation } from "@/lib/auth-errors"
import { usePasskeySupport } from "@/lib/auth-hooks"
import { createClient } from "@/lib/supabase/client"
import { toast } from "@/lib/toast"

type Passkey = {
  id: string
  friendly_name?: string
  created_at: string
  last_used_at?: string
}
type TotpFactor = { id: string; friendly_name?: string; created_at: string }

/** A recognisable default name, so the list never reads "Unnamed". */
function suggestPasskeyName(): string {
  if (typeof navigator === "undefined") return "Passkey"
  const ua = navigator.userAgent
  if (/iPhone|iPad/.test(ua)) return "iPhone"
  if (/Android/.test(ua)) return "Android phone"
  if (/Macintosh/.test(ua)) return "Mac"
  if (/Windows/.test(ua)) return "Windows PC"
  if (/Linux/.test(ua)) return "Linux device"
  return "Passkey"
}

/**
 * Two-factor settings: passkeys and an authenticator app.
 *
 * Passkeys go through `auth.passkey.*` (list / update / delete) rather than the
 * MFA factor API, because that is the surface that can name and rename them -
 * and a list of three identical "Unnamed" entries is useless when you need to
 * revoke the one from a laptop you no longer own.
 *
 * Rules this card enforces:
 *
 * - **Removing the last factor is spelled out, not just confirmed.** Supabase
 *   ships no backup codes, so the second factor IS the recovery story.
 * - **Naming happens at enrolment**, defaulted from the platform, because
 *   nobody goes back to name a credential afterwards.
 * - **A dismissed system prompt is not an error.** Cancelling the passkey sheet
 *   is a normal action and gets no red toast.
 */
export function TwoFactorCard() {
  const supabase = createClient()
  const passkeySupported = usePasskeySupport()

  // SWR rather than an effect: this is a fetch, and the codebase already reads
  // remote state this way everywhere else.
  const passkeys = useSWR<Passkey[]>("auth:passkeys", async () => {
    const { data, error } = await supabase.auth.passkey.list()
    if (error) return []
    return (data ?? []) as Passkey[]
  })
  const totp = useSWR<TotpFactor[]>("auth:totp", async () => {
    const { data, error } = await supabase.auth.mfa.listFactors()
    if (error) return []
    return (data?.totp ?? []) as TotpFactor[]
  })

  const [busy, setBusy] = useState<string | null>(null)

  // TOTP enrolment
  const [totpOpen, setTotpOpen] = useState(false)
  const [totpQr, setTotpQr] = useState<string | null>(null)
  const [totpSecret, setTotpSecret] = useState<string | null>(null)
  const [totpFactorId, setTotpFactorId] = useState<string | null>(null)
  const [totpCode, setTotpCode] = useState("")
  const [totpError, setTotpError] = useState(false)
  const [verifying, setVerifying] = useState(false)

  // Passkey naming
  const [namingId, setNamingId] = useState<string | null>(null)
  const [nameDraft, setNameDraft] = useState("")

  const [removal, setRemoval] = useState<
    { kind: "passkey" | "totp"; id: string; label: string } | null
  >(null)

  const passkeyList = passkeys.data ?? []
  const totpList = totp.data ?? []
  const total = passkeyList.length + totpList.length
  const loading = passkeys.isLoading || totp.isLoading

  async function addPasskey() {
    setBusy("passkey")
    try {
      const { data, error } = await supabase.auth.registerPasskey({})
      if (error) throw error
      await passkeys.mutate()
      // Name it immediately - the id comes back from registration, and asking
      // now is the only moment the user knows which device this is.
      if (data?.id) {
        setNamingId(data.id)
        setNameDraft(suggestPasskeyName())
      }
      toast.success("Passkey added")
    } catch (err) {
      if (isPasskeyCancellation(err)) return
      toast.error(authErrorMessage(err, "Could not add that passkey."))
    } finally {
      setBusy(null)
    }
  }

  async function savePasskeyName() {
    if (!namingId) return
    const friendlyName = nameDraft.trim().slice(0, 120)
    setNamingId(null)
    if (!friendlyName) return
    const { error } = await supabase.auth.passkey.update({
      passkeyId: namingId,
      friendlyName,
    })
    if (error) {
      toast.error(authErrorMessage(error, "Could not save that name."))
      return
    }
    await passkeys.mutate()
  }

  async function beginTotp() {
    setBusy("totp")
    try {
      // Read every factor, verified or not. Two things depend on it:
      const { data: existing } = await supabase.auth.mfa.listFactors()
      const all = (existing?.all ?? []) as {
        id: string
        friendly_name?: string
        factor_type: string
        status: string
      }[]

      // 1. Sweep abandoned enrolments. Closing the tab mid-setup leaves an
      //    `unverified` factor behind - useless (it cannot sign anyone in and
      //    does not raise the assurance level) but it still holds its name,
      //    and GoTrue rejects a second factor with a name already in use. So
      //    without this, one abandoned attempt blocks all future ones.
      const stale = all.filter(
        (f) => f.factor_type === "totp" && f.status === "unverified"
      )
      const removed = new Set<string>()
      for (const f of stale) {
        const { error: sweepError } = await supabase.auth.mfa
          .unenroll({ factorId: f.id })
          .catch(() => ({ error: new Error("unenroll failed") }))
        if (!sweepError) removed.add(f.id)
      }

      // 2. Pick a name nothing else is using. The old default embedded the
      //    date, so a second setup on the same day collided every time.
      //    Only names we CONFIRMED were removed count as free - assuming a
      //    failed sweep succeeded would pick a name still in use and fail the
      //    enrol for the same reason we are trying to avoid.
      const taken = new Set(
        all
          .filter((f) => !removed.has(f.id))
          .map((f) => f.friendly_name)
          .filter(Boolean)
      )
      const base = "Authenticator app"
      let friendlyName = base
      for (let n = 2; taken.has(friendlyName); n += 1) {
        friendlyName = `${base} ${n}`
      }

      const { data, error } = await supabase.auth.mfa.enroll({
        factorType: "totp",
        friendlyName,
      })
      if (error) throw error
      setTotpFactorId(data.id)
      setTotpQr(data.totp.qr_code)
      setTotpSecret(data.totp.secret)
      setTotpCode("")
      setTotpError(false)
      setTotpOpen(true)
    } catch (err) {
      toast.error(authErrorMessage(err, "Could not start setup."))
    } finally {
      setBusy(null)
    }
  }

  const confirmTotp = useCallback(
    async (code: string) => {
      if (!totpFactorId || verifying) return
      setVerifying(true)
      setTotpError(false)
      // The code is checked by Supabase, not here: challengeAndVerify recomputes
      // the HMAC from the shared secret server-side. The browser cannot approve
      // a code, and there is no client-side branch that could be edited to
      // accept one - failure comes back as an error from the server.
      const { error } = await supabase.auth.mfa.challengeAndVerify({
        factorId: totpFactorId,
        code,
      })
      if (error) {
        setVerifying(false)
        setTotpError(true)
        setTotpCode("")
        toast.error(authErrorMessage(error, "That code isn't right."))
        return
      }

      // Trust the OUTCOME, not the absence of an error. Re-read the factor
      // list and require this factor to actually appear as verified before
      // telling anyone two-factor is on. Without this, any future SDK or
      // gateway change that returned success without promoting the factor
      // would leave the user believing they are protected when they are not -
      // the worst possible failure mode for a security control.
      const { data: after } = await supabase.auth.mfa.listFactors()
      const confirmed = (after?.totp ?? []).some((f) => f.id === totpFactorId)
      setVerifying(false)
      if (!confirmed) {
        setTotpError(true)
        setTotpCode("")
        toast.error(
          "Could not confirm the app was linked. Please try setting it up again."
        )
        return
      }

      setTotpOpen(false)
      setTotpFactorId(null)
      toast.success("Authenticator app added")
      await totp.mutate()
    },
    [supabase, totpFactorId, verifying, totp]
  )

  /**
   * Abandoning setup leaves an `unverified` factor behind. It cannot sign
   * anyone in and does not raise the assurance level, but it lingers in the
   * account and muddies "do I have 2FA on?" - so clean it up.
   */
  const cancelTotp = useCallback(async () => {
    setTotpOpen(false)
    if (totpFactorId) {
      await supabase.auth.mfa
        .unenroll({ factorId: totpFactorId })
        .catch(() => {})
      setTotpFactorId(null)
      await totp.mutate()
    }
  }, [supabase, totpFactorId, totp])

  async function confirmRemoval() {
    if (!removal) return
    setBusy(removal.id)
    try {
      const { error } =
        removal.kind === "passkey"
          ? await supabase.auth.passkey.delete({ passkeyId: removal.id })
          : await supabase.auth.mfa.unenroll({ factorId: removal.id })
      if (error) throw error
      toast.success("Removed")
      await (removal.kind === "passkey" ? passkeys.mutate() : totp.mutate())
    } catch (err) {
      toast.error(authErrorMessage(err, "Could not remove that."))
    } finally {
      setBusy(null)
      setRemoval(null)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Two-factor authentication
          {total > 0 ? (
            <Badge
              variant="outline"
              className="gap-1 text-emerald-600 dark:text-emerald-400"
            >
              <ShieldCheck weight="fill" className="size-3.5" />
              On
            </Badge>
          ) : (
            <Badge variant="outline" className="text-muted-foreground">
              Off
            </Badge>
          )}
        </CardTitle>
        <CardDescription>
          A passkey signs you in on its own - no password, nothing to type. An
          authenticator app covers the times you sign in another way.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        {loading ? (
          <div className="space-y-2">
            <div className="h-14 animate-pulse rounded-xl bg-muted/60" />
            <div className="h-14 animate-pulse rounded-xl bg-muted/40" />
          </div>
        ) : (
          <>
            {total === 1 && (
              <div className="flex gap-2.5 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200">
                <Warning weight="fill" className="mt-0.5 size-4 shrink-0" />
                <p>
                  Add a second method. There are no backup codes, so if you lose
                  this one you would need support to get back in.
                </p>
              </div>
            )}

            <Group
              icon={<Fingerprint weight="duotone" className="size-5" />}
              title="Passkeys"
              hint="Face, fingerprint or device PIN. Syncs across your devices."
              items={passkeyList.map((p) => ({
                id: p.id,
                label: p.friendly_name || "Passkey",
                meta: p.last_used_at
                  ? `Last used ${new Date(p.last_used_at).toLocaleDateString()}`
                  : `Added ${new Date(p.created_at).toLocaleDateString()}`,
              }))}
              busy={busy}
              onRemove={(id, label) => setRemoval({ kind: "passkey", id, label })}
              action={
                passkeySupported === false ? (
                  <p className="text-xs text-muted-foreground">
                    Not supported in this browser
                  </p>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={busy === "passkey" || passkeySupported === null}
                    onClick={addPasskey}
                  >
                    {busy === "passkey" ? <Spin /> : <Key className="size-4" />}
                    Add passkey
                  </Button>
                )
              }
            />

            <Group
              icon={<DeviceMobile weight="duotone" className="size-5" />}
              title="Authenticator app"
              hint="A 6-digit code from Google Authenticator, 1Password, Authy…"
              items={totpList.map((f) => ({
                id: f.id,
                label: f.friendly_name || "Authenticator app",
                meta: `Added ${new Date(f.created_at).toLocaleDateString()}`,
              }))}
              busy={busy}
              onRemove={(id, label) => setRemoval({ kind: "totp", id, label })}
              action={
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy === "totp"}
                  onClick={beginTotp}
                >
                  {busy === "totp" ? (
                    <Spin />
                  ) : (
                    <DeviceMobile className="size-4" />
                  )}
                  Add app
                </Button>
              }
            />
          </>
        )}
      </CardContent>

      {/* Name the passkey just registered */}
      <Dialog
        open={!!namingId}
        onOpenChange={(open) => !open && savePasskeyName()}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Name this passkey</DialogTitle>
            <DialogDescription>
              So you can tell it apart later if you need to remove it.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={nameDraft}
            maxLength={120}
            autoFocus
            onChange={(e) => setNameDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && savePasskeyName()}
            placeholder="e.g. Work laptop"
          />
          <DialogFooter>
            <Button type="button" onClick={savePasskeyName}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* TOTP enrolment */}
      <Dialog open={totpOpen} onOpenChange={(open) => !open && cancelTotp()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Set up your authenticator app</DialogTitle>
            <DialogDescription>
              Scan this with your app, then enter the 6-digit code it shows.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {totpQr && (
              <div className="flex justify-center">
                <div className="rounded-xl bg-white p-3">
                  {/* Supabase returns an SVG data URI; next/image cannot run a
                      loader over one, hence unoptimized. */}
                  <Image
                    src={totpQr}
                    alt="QR code for your authenticator app"
                    width={180}
                    height={180}
                    unoptimized
                  />
                </div>
              </div>
            )}

            {totpSecret && (
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">
                  Can&apos;t scan? Enter this key instead
                </Label>
                <Input
                  readOnly
                  value={totpSecret}
                  onFocus={(e) => e.currentTarget.select()}
                  className="font-mono text-xs"
                />
              </div>
            )}

            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">
                Code from your app
              </Label>
              <OtpField
                value={totpCode}
                onChange={setTotpCode}
                onComplete={confirmTotp}
                disabled={verifying}
                invalid={totpError}
                length={TOTP_LENGTH}
              />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={cancelTotp}>
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!isCompleteCode(totpCode, TOTP_LENGTH) || verifying}
              onClick={() => confirmTotp(totpCode)}
            >
              {verifying ? <Spin /> : "Verify and enable"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Removal confirmation */}
      <Dialog open={!!removal} onOpenChange={(open) => !open && setRemoval(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Remove {removal?.label}?</DialogTitle>
            <DialogDescription>
              {total <= 1
                ? "This is your only second factor. Removing it turns two-factor authentication off for this account."
                : "You can add it again later. Your other methods keep working."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setRemoval(null)}
            >
              Keep it
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={busy === removal?.id}
              onClick={confirmRemoval}
            >
              {busy === removal?.id ? <Spin /> : "Remove"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

function Group({
  icon,
  title,
  hint,
  items,
  busy,
  action,
  onRemove,
}: {
  icon: React.ReactNode
  title: string
  hint: string
  items: { id: string; label: string; meta: string }[]
  busy: string | null
  action: React.ReactNode
  onRemove: (id: string, label: string) => void
}) {
  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex gap-2.5">
          <span className="mt-0.5 text-muted-foreground">{icon}</span>
          <div>
            <p className="text-sm font-medium">{title}</p>
            <p className="text-xs text-muted-foreground">{hint}</p>
          </div>
        </div>
        {action}
      </div>

      {items.length > 0 && (
        <ul className="space-y-1.5">
          {items.map((item) => (
            <li
              key={item.id}
              className="flex items-center justify-between gap-3 rounded-xl border bg-muted/30 px-3 py-2"
            >
              <div className="min-w-0">
                <p className="truncate text-sm">{item.label}</p>
                <p className="text-[11px] text-muted-foreground">{item.meta}</p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={`Remove ${item.label}`}
                disabled={busy === item.id}
                onClick={() => onRemove(item.id, item.label)}
                className="text-muted-foreground hover:text-destructive"
              >
                {busy === item.id ? <Spin /> : <Trash className="size-4" />}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
