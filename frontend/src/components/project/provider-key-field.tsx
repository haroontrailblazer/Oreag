"use client"

import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"

/**
 * Per-project key entry for one role (LLM or embedding).
 *
 * Three states:
 * - An override key is stored for the selected provider → masked chip
 *   (`Project key ••••1234`) with Replace / Use account key (or Remove, which
 *   asks for confirmation since it leaves the project with no key).
 * - No override but the account already has a key for this provider → a note
 *   with an opt-in to set a project key.
 * - No key available for this provider → a password input.
 *
 * The Save / Cancel buttons for the input live on the parent card (they only
 * appear once the input is shown).
 */
export function ProviderKeyField({
  provider,
  last4,
  accountHasKey,
  value,
  onChange,
  editing,
  onEditingChange,
  onRemove,
  busy = false,
}: {
  provider: string
  /** Stored override last4 for THIS provider, or null when none applies. */
  last4: string | null
  accountHasKey: boolean
  value: string
  onChange: (value: string) => void
  editing: boolean
  onEditingChange: (editing: boolean) => void
  onRemove: () => void
  busy?: boolean
}) {
  const [confirmingRemove, setConfirmingRemove] = useState(false)

  if (last4 && !editing) {
    return (
      <>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-mono">Project key ••••{last4}</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => onEditingChange(true)}
          >
            Replace
          </Button>
          {accountHasKey ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={onRemove}
            >
              Use account key
            </Button>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => setConfirmingRemove(true)}
            >
              Remove
            </Button>
          )}
        </div>

        <Dialog open={confirmingRemove} onOpenChange={setConfirmingRemove}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Remove this project key?</DialogTitle>
              <DialogDescription>
                The {provider} key will be permanently deleted from this project.
                There&apos;s no account {provider} key to fall back on, so this
                project won&apos;t be able to use {provider} until you add a new
                key.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setConfirmingRemove(false)}
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                disabled={busy}
                onClick={() => {
                  setConfirmingRemove(false)
                  onRemove()
                }}
              >
                Delete
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </>
    )
  }

  if (!last4 && accountHasKey && !editing) {
    return (
      <p className="text-sm text-foreground/80">
        Using your account {provider} key.{" "}
        <button
          type="button"
          className="font-medium underline underline-offset-2"
          onClick={() => onEditingChange(true)}
        >
          Use a project key instead
        </button>
      </p>
    )
  }

  return (
    <div className="space-y-1.5">
      <Input
        type="password"
        autoComplete="off"
        placeholder={`Paste your ${provider} key for this project`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <p className="text-xs text-foreground/70">
        {accountHasKey
          ? `Optional — leave blank to keep using your account ${provider} key.`
          : `${provider} has no account key — paste one to use it for this project.`}
      </p>
    </div>
  )
}
