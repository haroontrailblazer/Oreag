import { createBrowserClient } from "@supabase/ssr"

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      auth: {
        // Passkeys sit behind an opt-in flag in auth-js. Without it every
        // passkey method - signInWithPasskey, registerPasskey, auth.passkey.* -
        // THROWS at call time rather than being merely absent, so this line is
        // load-bearing. Removing it breaks passkey sign-in at runtime with no
        // type error to catch it.
        experimental: { passkey: true },
      },
    }
  )
}
