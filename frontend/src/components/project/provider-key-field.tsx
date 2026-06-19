"use client"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

/**
 * Per-project key entry for one role (LLM or embedding).
 *
 * Three states:
 * - An override key is stored for the selected provider → masked chip
 *   (`Project key ••••1234`) with Replace / Use account key (or Remove).
 * - No override but the account already has a key for this provider → a muted
 *   "using your account key" note with an opt-in to set a project key.
 * - No key available for this provider → a password input (required to use it).
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
  if (last4 && !editing) {
    return (
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
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={onRemove}
        >
          {accountHasKey ? "Use account key" : "Remove"}
        </Button>
      </div>
    )
  }

  if (!last4 && accountHasKey && !editing) {
    return (
      <p className="text-sm text-muted-foreground">
        Using your account {provider} key.{" "}
        <button
          type="button"
          className="underline"
          onClick={() => onEditingChange(true)}
        >
          Use a project key instead
        </button>
      </p>
    )
  }

  const canCancel = Boolean(last4) || accountHasKey
  return (
    <div className="space-y-1.5">
      <Input
        type="password"
        autoComplete="off"
        placeholder={`Paste your ${provider} key for this project`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <p className="text-xs text-muted-foreground">
        {accountHasKey
          ? `Optional — leave blank to keep using your account ${provider} key.`
          : `${provider} has no account key — paste one to use it for this project.`}
        {canCancel ? (
          <>
            {" "}
            <button
              type="button"
              className="underline"
              onClick={() => {
                onChange("")
                onEditingChange(false)
              }}
            >
              Cancel
            </button>
          </>
        ) : null}
      </p>
    </div>
  )
}
