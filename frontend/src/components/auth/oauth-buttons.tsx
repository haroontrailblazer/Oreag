"use client"

import { useRouter } from "next/navigation"
import { useCallback, useEffect, useRef, useState } from "react"

import { Spin } from "@/components/ui/loader"
import { createClient } from "@/lib/supabase/client"
import { toast } from "@/lib/toast"
import { cn } from "@/lib/utils"

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
 * The consent flow runs in a POPUP, not by navigating this tab away. The reason
 * is the Back button: a full redirect puts the provider's account-chooser and
 * consent screens into THIS tab's history, and no code on our side can remove a
 * cross-origin entry - so after signing in, one press of Back landed the user
 * back on Google's account picker. Run in a popup, those pages live and die in
 * the popup's history, and the main tab goes straight from the login page to
 * the dashboard.
 *
 * Popup blockers are handled rather than ignored: the window is opened
 * SYNCHRONOUSLY inside the click handler (a popup opened after an await is
 * blocked by every browser), and if it is blocked anyway the code falls back to
 * the old full-page redirect. Signing in always works; only the Back-button
 * polish is lost.
 */
export function OAuthButtons({
  only,
  className,
  buttonClassName,
}: {
  only?: Provider[]
  className?: string
  buttonClassName?: string
} = {}) {
  const router = useRouter()
  const [redirecting, setRedirecting] = useState<Provider | null>(null)
  const popupRef = useRef<Window | null>(null)
  const providers: Provider[] = only ?? ["google", "github"]

  const finish = useCallback(() => {
    // replace, so the login page is not left behind for Back to return to.
    router.replace("/dashboard")
    router.refresh()
  }, [router])

  // The popup reports back here when /auth/callback has exchanged the code.
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      // Same-origin only. Without this check any page could post a fake
      // success and navigate the user into the dashboard shell.
      if (event.origin !== window.location.origin) return
      const payload = event.data as { type?: string; ok?: boolean } | null
      if (payload?.type !== "oreag-oauth") return
      popupRef.current?.close()
      popupRef.current = null
      setRedirecting(null)
      if (payload.ok) finish()
      else toast.error("Sign-in was not completed.")
    }
    window.addEventListener("message", onMessage)
    return () => window.removeEventListener("message", onMessage)
  }, [finish])

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

    // Opened BEFORE the await. A window.open() that happens after an async hop
    // has lost the user-gesture context and is blocked by every browser.
    const popup = window.open(
      "about:blank",
      "oreag-oauth",
      "width=520,height=680,menubar=no,toolbar=no"
    )

    const { data, error } = await createClient().auth.signInWithOAuth({
      provider,
      options: {
        redirectTo: `${location.origin}/auth/callback${popup ? "?popup=1" : ""}`,
        skipBrowserRedirect: true,
      },
    })

    if (error || !data?.url) {
      popup?.close()
      setRedirecting(null)
      toast.error(error?.message ?? "Could not start sign-in.")
      return
    }

    if (!popup || popup.closed) {
      // Blocked. Fall back to the classic redirect so sign-in still works.
      window.location.assign(data.url)
      return
    }

    popup.location.replace(data.url)
    popupRef.current = popup

    // The user may simply close the window. Without this the button would spin
    // for ever with no way back.
    const watch = window.setInterval(() => {
      if (popupRef.current?.closed) {
        window.clearInterval(watch)
        popupRef.current = null
        setRedirecting((current) => (current === provider ? null : current))
      }
    }, 500)
  }

  const btn = cn(
    "flex h-11 flex-1 items-center justify-center gap-2 rounded-none border bg-card text-sm font-medium transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-60",
    buttonClassName
  )

  return (
    <div className={cn("flex items-center gap-3", className)}>
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
