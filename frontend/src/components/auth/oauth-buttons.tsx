"use client"

import { useEffect, useState } from "react"

import { Spin } from "@/components/ui/loader"
import { createClient } from "@/lib/supabase/client"
import { toast } from "@/lib/toast"

type Provider = "google" | "github"

/** Official Google "G" in brand colors (per Google's sign-in guidelines). */
function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-4 shrink-0" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M23.52 12.27c0-.85-.08-1.66-.22-2.45H12v4.64h6.46a5.53 5.53 0 0 1-2.4 3.62v3h3.88c2.26-2.09 3.58-5.17 3.58-8.81Z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.96-1.07 7.94-2.91l-3.88-3.01c-1.07.72-2.45 1.15-4.06 1.15-3.13 0-5.78-2.11-6.72-4.95H1.27v3.11A11.99 11.99 0 0 0 12 24Z"
      />
      <path
        fill="#FBBC05"
        d="M5.28 14.28a7.2 7.2 0 0 1 0-4.56V6.61H1.27a12 12 0 0 0 0 10.78l4.01-3.11Z"
      />
      <path
        fill="#EA4335"
        d="M12 4.77c1.76 0 3.34.61 4.59 1.8l3.44-3.44C17.95 1.19 15.24 0 12 0A11.99 11.99 0 0 0 1.27 6.61l4.01 3.11C6.22 6.88 8.87 4.77 12 4.77Z"
      />
    </svg>
  )
}

function GitHubIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="size-4 shrink-0 fill-current"
      aria-hidden="true"
    >
      <path d="M12 .3a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.03c-3.34.73-4.04-1.61-4.04-1.61-.55-1.39-1.33-1.76-1.33-1.76-1.09-.74.08-.73.08-.73 1.2.09 1.84 1.24 1.84 1.24 1.07 1.83 2.81 1.3 3.5 1 .1-.78.42-1.31.76-1.61-2.66-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.13-.3-.54-1.52.11-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6.01 0c2.29-1.55 3.29-1.23 3.29-1.23.66 1.66.25 2.88.12 3.18.77.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.63-5.49 5.92.43.38.82 1.11.82 2.24v3.32c0 .32.21.7.83.58A12 12 0 0 0 12 .3Z" />
    </svg>
  )
}

/**
 * "Continue with Google / GitHub" buttons for the auth pages.
 *
 * signInWithOAuth navigates the browser away to the provider; the button
 * keeps its "Redirecting…" state until that navigation happens, so there is
 * deliberately no success-path state reset. The existing /auth/callback route
 * exchanges the code for a session when the user lands back.
 */
export function OAuthButtons({ only }: { only?: Provider[] } = {}) {
  const [redirecting, setRedirecting] = useState<Provider | null>(null)
  const providers: Provider[] = only ?? ["google", "github"]

  // Clear the spinner if the user comes BACK to this page (e.g. presses back
  // from the Google/GitHub screen). Browsers restore the page from bfcache with
  // React state frozen, so `redirecting` would otherwise stay stuck spinning.
  useEffect(() => {
    const reset = () => setRedirecting(null)
    window.addEventListener("pageshow", reset)
    return () => window.removeEventListener("pageshow", reset)
  }, [])

  async function handleOAuth(provider: Provider) {
    setRedirecting(provider)
    const { error } = await createClient().auth.signInWithOAuth({
      provider,
      options: { redirectTo: `${location.origin}/auth/callback` },
    })
    if (error) {
      setRedirecting(null)
      toast.error(error.message)
    }
  }

  const btn =
    "flex h-11 flex-1 items-center justify-center gap-2 rounded-xl border bg-card text-sm font-medium transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-60"

  return (
    <div className="flex items-center gap-3">
      {providers.includes("google") && (
        <button
          type="button"
          className={btn}
          disabled={redirecting !== null}
          onClick={() => handleOAuth("google")}
          aria-label="Continue with Google"
        >
          <GoogleIcon />
          Google
          {redirecting === "google" && <Spin />}
        </button>
      )}
      {providers.includes("github") && (
        <button
          type="button"
          className={btn}
          disabled={redirecting !== null}
          onClick={() => handleOAuth("github")}
          aria-label="Continue with GitHub"
        >
          <GitHubIcon />
          GitHub
          {redirecting === "github" && <Spin />}
        </button>
      )}
    </div>
  )
}

/** Faint centered word separator (just "or", matching the reference design). */
export function OrDivider({ label = "or" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3" role="separator">
      <span className="h-px flex-1 bg-border" />
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span className="h-px flex-1 bg-border" />
    </div>
  )
}
