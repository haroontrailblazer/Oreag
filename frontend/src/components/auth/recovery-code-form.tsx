"use client"

import { Key, SignOut } from "@phosphor-icons/react/dist/ssr"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Spin } from "@/components/ui/loader"
import { api } from "@/lib/api"
import { toast } from "@/lib/toast"

/**
 * "Lost your device?" escape hatch, shown under every authenticator prompt.
 *
 * Lives in one component because there are TWO places a code can be demanded -
 * the login page's own step, and the step-up page reached when the API refuses
 * an under-levelled session - and a way out that exists on only one of them is
 * not a way out. Anyone who lost their phone during sign-in would otherwise
 * have to guess that a different page offers the option.
 *
 * Consuming a code REMOVES the account's second factors rather than granting
 * aal2, which only Supabase can issue; see the endpoint and migration 0021 for
 * why that is the only workable shape.
 */
export function RecoveryCodeForm({ onSignOut }: { onSignOut: () => void }) {
  const [open, setOpen] = useState(false)
  const [code, setCode] = useState("")
  const [busy, setBusy] = useState(false)

  async function redeem() {
    const value = code.trim()
    if (!value || busy) return
    setBusy(true)
    try {
      await api("/api/account/recovery-codes/consume", {
        method: "POST",
        body: JSON.stringify({ code: value }),
      })
      toast.success("Recovery code accepted", {
        description: "Two-factor is now off. Set it up again from Settings.",
      })
      // Hard navigation: every SWR cache in the app is holding a 403 from
      // before this moment, and a soft push would reuse them.
      window.location.replace("/settings/profile")
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "That recovery code isn't valid."
      )
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      {open ? (
        <div className="space-y-3 rounded-xl border bg-muted/30 p-3">
          <p className="text-xs text-muted-foreground">
            Enter one of the recovery codes you saved when you set up two-factor.
            Each works once, and using one turns two-factor off so you can set it
            up again.
          </p>
          <Input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && redeem()}
            placeholder="XXXXXXXXXX"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            className="text-center font-mono tracking-widest"
          />
          <div className="flex gap-2">
            <Button
              type="button"
              variant="ghost"
              className="flex-1"
              onClick={() => {
                setOpen(false)
                setCode("")
              }}
            >
              Back
            </Button>
            <Button
              type="button"
              className="flex-1"
              disabled={!code.trim() || busy}
              onClick={redeem}
            >
              {busy ? <Spin /> : "Use code"}
            </Button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex w-full items-center justify-center gap-1.5 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          <Key className="size-3.5" />
          Lost your device? Use a recovery code
        </button>
      )}

      <button
        type="button"
        onClick={onSignOut}
        className="flex w-full items-center justify-center gap-1.5 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
      >
        <SignOut className="size-3.5" />
        Sign out instead
      </button>
    </div>
  )
}
