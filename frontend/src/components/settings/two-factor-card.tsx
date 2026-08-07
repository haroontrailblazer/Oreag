"use client"

import {
  DeviceMobileIcon as DeviceMobile,
  FingerprintIcon as Fingerprint,
  KeyIcon as Key,
  ShieldCheckIcon as ShieldCheck,
  TrashIcon as Trash,
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
import { Switch } from "@/components/ui/switch"
import { api } from "@/lib/api"
import { authErrorMessage, isPasskeyCancellation } from "@/lib/auth-errors"
import {
  MFA_FACTORS_KEY,
  SECURITY_PREFS_KEY,
  PASSKEYS_KEY,
  RECOVERY_KEY,
  TOTP_KEY,
  fetchMfaFactors,
  fetchPasskeys,
  fetchRecoveryCount,
  fetchSecurityPrefs,
  fetchTotpFactors,
  type MfaFactor,
  type Passkey,
  type SecurityPrefs,
  type TotpFactor,
} from "@/lib/settings-data"
import { usePasskeySupport } from "@/lib/auth-hooks"
import { createClient } from "@/lib/supabase/client"
import { toast } from "@/lib/toast"

// Types live with the fetchers in lib/settings-data so both consumers agree.

/** Line break for the copied / downloaded recovery-code list. */
const NEWLINE = "\n"

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
 * Two-factor settings: a master switch over passkeys and an authenticator app.
 *
 * Both are the mechanisms that already worked here:
 *
 * - **Passkeys** go through `auth.passkey.*` / `registerPasskey()`. One signs
 *   in on its own, in a single step, and lands at aal2 - so nothing is asked
 *   for behind it.
 * - **The authenticator app** is a TOTP factor in `auth.mfa_factors`, and it is
 *   the one the sign-in challenge actually presents.
 *
 * NOT `mfa.webauthn.register()` - enrolling a passkey as a second FACTOR is a
 * separate Supabase feature, and this project answers
 * `422 "MFA enroll is disabled for WebAuthn"` for it. Verified against the live
 * API; TOTP enrols 200 on the same account, which ruled out the browser and the
 * call shape.
 *
 * THE SWITCH controls whether sign-in asks for a second step at all. Turning it
 * off keeps every method enrolled and simply stops the prompt (migration 0027),
 * because `mfa.unenroll()` would delete the TOTP secret and force a fresh QR
 * scan to turn it back on.
 *
 * Rules this card enforces:
 *
 * - **Removing the last method is spelled out, not just confirmed.** Supabase
 *   ships no backup codes, so recovery codes are the recovery story.
 * - **One method is a finished state.** A passkey and an authenticator are
 *   alternatives, not a set to complete, so nothing nags for the second.
 * - **A dismissed system prompt is not an error.** Cancelling the passkey sheet
 *   is a normal action and gets no red toast.
 */
export function TwoFactorCard() {
  const supabase = createClient()
  const passkeySupported = usePasskeySupport()

  // SWR rather than an effect: this is a fetch, and the codebase already reads
  // remote state this way everywhere else.
  //
  // Key AND fetcher both come from lib/settings-data so the dashboard can warm
  // these on entry. An inline closure here would be a different function for
  // the same key, so the preloaded value would be ignored and this page would
  // still open cold - which is the whole point of hoisting them.
  const passkeys = useSWR<Passkey[]>(PASSKEYS_KEY, fetchPasskeys)
  const totp = useSWR<TotpFactor[]>(TOTP_KEY, fetchTotpFactors)
  // Webauthn factors appear only in listFactors().all, so the TOTP-only
  // fetcher above cannot see a passkey enrolled as a GATE.
  const mfaFactors = useSWR<MfaFactor[]>(MFA_FACTORS_KEY, fetchMfaFactors)
  // Whether sign-in challenges the factor. Separate from whether one EXISTS -
  // that is the whole point of the switch below.
  const prefs = useSWR<SecurityPrefs>(SECURITY_PREFS_KEY, fetchSecurityPrefs)

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

  // Recovery codes, shown exactly once. Supabase has no backup codes of its
  // own, so without these a lost authenticator is a permanent lockout.
  const [codes, setCodes] = useState<string[] | null>(null)
  const [issuing, setIssuing] = useState(false)

  // Confirmation for the master switch. Turning 2FA off removes every factor,
  // so it is spelled out rather than flipped silently.
  const [disableOpen, setDisableOpen] = useState(false)
  const [chooseOpen, setChooseOpen] = useState(false)

  const [removal, setRemoval] = useState<
    | {
        /** Different tables, different removal APIs. */
        kind: "passkey" | "totp"
        id: string
        label: string
      }
    | null
  >(null)

  const recovery = useSWR<{ remaining: number }>(
    RECOVERY_KEY,
    fetchRecoveryCount
  )
  const passkeyList = passkeys.data ?? []
  const totpList = totp.data ?? []
  // Passkeys enrolled as a SECOND FACTOR. Distinct from passkeyList above,
  // which holds LOGIN passkeys (auth.webauthn_credentials) - those sign in on
  // their own and cannot gate anything. See lib/mfa.ts.
  const total = passkeyList.length + totpList.length
  const twoFactorOn = total > 0 && prefs.data?.two_factor_prompt !== false

  /**
   * Offer "add a passkey" only when the account HAS none - counting login
   * passkeys as well as factors.
   *
   * The two live in different tables and only one of them gates a sign-in, but
   * the user does not see two kinds of passkey: they see the passkey they
   * already registered, next to a button telling them to register one. Whatever
   * the internals, "add" is the wrong word once one exists.
   */
  /**
   * Offer "add a passkey" only when the account has none.
   *
   * Deliberately NOT folding in browser support: the two are different answers
   * to the user - "you already have one" hides the row, "this browser cannot"
   * has to be SAID, or the option looks arbitrarily missing on that device.
   */
  const canAddPasskey = passkeyList.length === 0
  const loading = passkeys.isLoading || totp.isLoading || mfaFactors.isLoading

  async function refreshFactors() {
    await Promise.all([mfaFactors.mutate(), totp.mutate(), passkeys.mutate()])
  }

  /**
   * Add a LOGIN passkey - `registerPasskey()`, the same call that has always
   * worked here.
   *
   * NOT `mfa.webauthn.register()`. That enrols a passkey as a second FACTOR,
   * which is a different table and a different Supabase feature - and this
   * project returns `422 "MFA enroll is disabled for WebAuthn"` for it, so
   * every attempt failed. Verified directly against the API; TOTP enrols 200 on
   * the same account, which is what ruled out the browser and the call shape.
   *
   * A login passkey signs in on its own and lands at aal2, so it needs no
   * second step behind it - and its `webauthn` entry in `amr` also satisfies
   * the email-confirmation gate in backend/app/auth/jwt.py.
   */
  async function addPasskey() {
    setBusy("passkey")
    try {
      const { data, error } = await supabase.auth.registerPasskey({})
      if (error) throw error
      // React the instant the ceremony returns. Putting the naming dialog
      // behind a full refetch left the UI frozen for a beat after the
      // fingerprint, with nothing to show for it.
      if (data?.id) {
        setNamingId(data.id)
        setNameDraft(suggestPasskeyName())
      }
      toast.success("Passkey added")
      void passkeys.mutate()
    } catch (err) {
      if (isPasskeyCancellation(err)) return
      toast.error(authErrorMessage(err, "Could not add that passkey."))
    } finally {
      setBusy(null)
    }
  }

  /**
   * Turn the sign-in challenge OFF while KEEPING every enrolled factor.
   *
   * It used to unenrol them, because Supabase has no disabled-factor state -
   * but that deletes the TOTP secret, so switching back on meant scanning a
   * fresh QR code. Nobody expects a toggle to destroy their setup. The factor
   * stays; a server-side preference (migration 0027) tells the gate not to ask.
   *
   * Written server-side, never in user_metadata: metadata rides in the JWT and
   * is writable by the user's own token, so a stolen aal1 session could switch
   * its own second factor off - a complete bypass.
   */
  async function setTwoFactorPrompt(enabled: boolean) {
    setBusy("prompt")
    try {
      await api(SECURITY_PREFS_KEY, {
        method: "PUT",
        body: JSON.stringify({ two_factor_prompt: enabled }),
      })
      await prefs.mutate()
      toast.success(enabled ? "Two-factor turned on" : "Two-factor turned off")
    } catch (err) {
      toast.error(authErrorMessage(err, "Could not change that setting."))
    } finally {
      setBusy(null)
      setDisableOpen(false)
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

  const issueRecoveryCodes = useCallback(async () => {
    setIssuing(true)
    try {
      const res = await api<{ codes: string[] }>("/api/account/recovery-codes", {
        method: "POST",
      })
      setCodes(res.codes)
      void recovery.mutate()
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Could not create recovery codes."
      )
    } finally {
      setIssuing(false)
    }
  }, [recovery])

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
      // BOTH caches. `totp` drives the list, but `mfaFactors` is what
      // disableTwoFactor() iterates - leaving it stale means the master switch
      // would skip the factor just added and report success without removing it.
      await Promise.all([totp.mutate(), mfaFactors.mutate()])
      // Straight into the codes: this is the only moment the user is thinking
      // about recovery, and the only time the codes can ever be displayed.
      if ((recovery.data?.remaining ?? 0) === 0) void issueRecoveryCodes()
    },
    [
      supabase,
      totpFactorId,
      verifying,
      totp,
      mfaFactors,
      recovery,
      issueRecoveryCodes,
    ]
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
      await Promise.all([totp.mutate(), mfaFactors.mutate()])
    }
  }, [supabase, totpFactorId, totp, mfaFactors])


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
      // Refresh every list: a webauthn factor and a login passkey are held in
      // different caches, and getting this wrong leaves a removed credential
      // on screen until a reload.
      await refreshFactors()
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
          Ask for a second proof after your password. A passkey uses your face,
          fingerprint or device PIN; an authenticator app gives you a code.
          Either one is enough - you do not need both.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* The master switch. It reflects whether ANY factor is enrolled,
            because that is the only thing that actually changes sign-in - a
            separate stored "enabled" flag could disagree with reality and
            would be the thing users trusted. Turning it on has to enrol
            something, so it opens the chooser rather than flipping. */}
        <div className="flex items-center justify-between gap-4 rounded-xl border bg-muted/30 p-3">
          <div className="min-w-0">
            <p className="text-sm font-medium">
              {twoFactorOn ? "Two-factor is on" : "Two-factor is off"}
            </p>
            <p className="text-xs text-muted-foreground">
              {twoFactorOn
                ? "You'll confirm it's you after signing in."
                : "Sign-in only needs your password."}
            </p>
          </div>
          <Switch
            label="Two-factor authentication"
            checked={twoFactorOn}
            busy={busy === "prompt"}
            disabled={loading}
            onCheckedChange={(next) => {
              // ON with a factor already enrolled just re-enables the prompt -
              // no need to make them add a second one they did not ask for.
              if (next) {
                if (total > 0) void setTwoFactorPrompt(true)
                else setChooseOpen(true)
                return
              }
              setDisableOpen(true)
            }}
          />
        </div>

        {loading ? (
          <div className="space-y-2">
            <div className="h-14 animate-pulse rounded-xl bg-muted/60" />
            <div className="h-14 animate-pulse rounded-xl bg-muted/40" />
          </div>
        ) : (
          <>
            {/* No "add a second method" nag. A passkey and an authenticator
                are alternatives, not a set to complete - one is a legitimate
                finished state, and the banner told people otherwise every time
                they opened this page. Recovery codes cover the lost-device
                case, and they have their own row below. */}
            <Group
              icon={<Fingerprint weight="duotone" className="size-5" />}
              title="Passkeys"
              hint="Face, fingerprint or device PIN. Asked for after your password."
              items={passkeyList.map((p) => ({
                id: p.id,
                label: p.friendly_name || "Passkey",
                meta: p.last_used_at
                  ? `Last used ${new Date(p.last_used_at).toLocaleDateString()}`
                  : `Added ${new Date(p.created_at).toLocaleDateString()}`,
              }))}
              busy={busy}
              onRemove={(id, label) => setRemoval({ kind: "passkey", id, label })}
              // Once one is enrolled the button goes away: this method is
              // set up, and the card should read as done rather than as an
              // open invitation to keep adding. Remove the passkey and it
              // comes back.
              action={
                !canAddPasskey ? null : passkeySupported === false ? (
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

            {total > 0 && (
              <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border bg-muted/30 p-3">
                <div className="flex gap-2.5">
                  <Key weight="duotone" className="mt-0.5 size-5 text-muted-foreground" />
                  <div>
                    <p className="text-sm font-medium">Recovery codes</p>
                    <p className="text-xs text-muted-foreground">
                      {recovery.data
                        ? `${recovery.data.remaining} unused - your way back in if you lose a device`
                        : "Your way back in if you lose a device"}
                    </p>
                  </div>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={issuing}
                  onClick={issueRecoveryCodes}
                >
                  {issuing ? <Spin /> : null}
                  {(recovery.data?.remaining ?? 0) > 0 ? "Regenerate" : "Generate"}
                </Button>
              </div>
            )}

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
                totpList.length > 0 ? null : (
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
                )
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

      {/* Recovery codes - shown once, never retrievable afterwards. */}
      <Dialog open={!!codes} onOpenChange={(open) => !open && setCodes(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Save your recovery codes</DialogTitle>
            <DialogDescription>
              Each code works once. Keep them somewhere you can reach without
              this device - they are the only way back in if you lose your
              authenticator.
            </DialogDescription>
          </DialogHeader>

          <div className="grid grid-cols-2 gap-2 rounded-xl border bg-muted/40 p-3 font-mono text-sm">
            {(codes ?? []).map((c) => (
              <span key={c} className="tracking-widest">
                {c}
              </span>
            ))}
          </div>

          <p className="text-xs text-muted-foreground">
            This is the only time they are shown. Only a one-way hash is stored,
            so they cannot be looked up later - regenerate if you lose them.
          </p>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                navigator.clipboard.writeText((codes ?? []).join(NEWLINE))
                toast.success("Copied")
              }}
            >
              Copy
            </Button>
            <Button
              type="button"
              onClick={() => {
                const blob = new Blob(
                  [
                    `Oreag recovery codes${NEWLINE}`,
                    `Each code can be used once.${NEWLINE}${NEWLINE}`,
                    (codes ?? []).join(NEWLINE),
                    NEWLINE,
                  ],
                  { type: "text/plain" }
                )
                const url = URL.createObjectURL(blob)
                const a = document.createElement("a")
                a.href = url
                a.download = "oreag-recovery-codes.txt"
                a.click()
                URL.revokeObjectURL(url)
                setCodes(null)
              }}
            >
              Download and close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Removal confirmation */}
      {/* Turning the master switch ON has to enrol something, so it asks WHAT
          rather than silently picking. Passkey is listed first and described in
          plain terms: it is the faster one and the one most people already have
          hardware for. */}
      <Dialog open={chooseOpen} onOpenChange={setChooseOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Turn on two-factor</DialogTitle>
            <DialogDescription>
              Pick how you want to confirm it&rsquo;s you when signing in.
            </DialogDescription>
          </DialogHeader>

          {/* Plain <button> elements, not <Button>. The shadcn button centres
              its content and sets whitespace-nowrap, so a two-line label inside
              it collapsed and overflowed - these are cards, not buttons, and
              styling them directly is less code than overriding all of that. */}
          <div className="grid gap-2">
            {canAddPasskey && (
              <button
                type="button"
                disabled={busy === "passkey" || passkeySupported === null}
                onClick={() => {
                  setChooseOpen(false)
                  void addPasskey()
                }}
                className="flex w-full items-start gap-3 rounded-xl border bg-card p-4 text-left transition-colors hover:border-foreground/20 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
              >
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
                  <Fingerprint weight="duotone" className="size-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">Passkey</span>
                  <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                    Face, fingerprint or device PIN. Nothing to type.
                  </span>
                </span>
              </button>
            )}

            <button
              type="button"
              onClick={() => {
                setChooseOpen(false)
                void beginTotp()
              }}
              className="flex w-full items-start gap-3 rounded-xl border bg-card p-4 text-left transition-colors hover:border-foreground/20 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
                <DeviceMobile weight="duotone" className="size-5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">
                  Authenticator app
                </span>
                <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                  A 6-digit code from Google Authenticator, 1Password or Authy.
                </span>
              </span>
            </button>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setChooseOpen(false)}>
              Cancel
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={disableOpen} onOpenChange={(open) => !open && setDisableOpen(false)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Turn off two-factor?</DialogTitle>
            <DialogDescription>
              Your password alone will sign you in.
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {total > 0
              ? "Your methods stay set up - we just stop asking for them. Turn this back on any time without scanning anything again."
              : "You can turn this back on whenever you like."}
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              autoFocus
              onClick={() => setDisableOpen(false)}
            >
              Cancel
            </Button>
            <Button
              disabled={busy === "prompt"}
              onClick={() => void setTwoFactorPrompt(false)}
            >
              {busy === "prompt" ? <Spin /> : null}
              Turn off
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
