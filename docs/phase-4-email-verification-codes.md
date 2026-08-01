# Phase 4 — Email verification codes

> **Status: planned, not implemented.** Written 2026-08-01. Phase 5 (subscriptions
> & payments) was Phase 4 until this document renumbered it.

## Context

Today every identity-proving step in Oreag is a **clicked link**. That works, but
links have failure modes codes don't: they break when the email is opened in a
different browser from the one that started the flow, corporate mail scanners
sometimes *consume* the one-time token before the human clicks it, and on a phone
the app-switch is friction. The reset page already carries a dead-end branch for
exactly this ("This password reset link is invalid or has expired").

This phase adds a 6-digit code alongside the link on every flow, and adds a code
as a **second factor at login**.

---

## Part 1 — The existing flow, as built today

### Signup
`frontend/src/app/(auth)/signup/page.tsx:42` calls `supabase.auth.signUp({ email,
password, options: { emailRedirectTo: '/auth/callback' } })`.

- Supabase emails a confirmation link.
- Already-registered emails are detected via Supabase's enumeration protection
  (a user with `identities: []`) and steered to "Sign in instead". Keep this.
- If confirmation is disabled a session comes back immediately; otherwise the
  page shows "Check your inbox".

### Email confirmation
Two handlers exist, and they are **not** equivalent:

- `frontend/src/app/auth/confirm/route.ts` — the **token_hash** path. Reads
  `?token_hash=&type=` and calls `verifyOtp({ type, token_hash })`. Its own
  comment explains why: `verifyOtp` works regardless of which browser opens the
  link, which the PKCE `?code=` flow cannot guarantee.
- `frontend/src/app/auth/callback/route.ts` — the **PKCE** path. Reads `?code=`
  and calls `exchangeCodeForSession(code)`. This one *does* break across
  browsers.

Both clamp `?next=` to internal paths only (no open redirect).

Note the inconsistency: signup and password reset both point at
`/auth/callback` (the fragile PKCE route), while the more robust `/auth/confirm`
route exists but nothing currently links to it.

### Password reset
`frontend/src/app/(auth)/login/page.tsx:120` calls `resetPasswordForEmail(email,
{ redirectTo: '/auth/callback?next=/auth/reset-password' })`. The link
establishes a recovery session, then `frontend/src/app/auth/reset-password/page.tsx`
checks `getSession()` and renders `SetPasswordForm`, which calls
`updateUser({ password })`. No session means the "link is invalid or has expired"
dead end.

The page already guards double-sends (`forgot: idle | sending | sent`) and
translates Supabase's 429 into "try again in about an hour" — evidence the
default SMTP rate limit is being hit today.

### Password change while signed in
`frontend/src/app/(dashboard)/settings/profile/page.tsx:411` renders the same
`SetPasswordForm` → `updateUser({ password })`. **No re-verification of any
kind.** A live stolen session can change the password outright.

### Resend verification
`profile/page.tsx:208` calls `auth.resend({ type: 'signup', email })`, shown only
while `email_confirmed_at` is null.

### Login
Identifier-first, three steps (`email` → `password` | `oauth`).
`POST /api/auth/methods` (`frontend/src/app/api/auth/methods/route.ts`) calls the
`auth_methods_for_email` SECURITY DEFINER RPC (migration
`0017_auth_methods_rpc.sql`) with the service-role key to report
`{ exists, has_password, providers }`, then routes to the password field or the
right OAuth button.

**Two architectural facts from this file constrain everything below:**

1. It deliberately runs as a **Next.js route, not FastAPI** — its comment says
   so: "always up with this page, so the routing works even when the FastAPI
   backend is asleep." Any login-blocking logic must live in Next.js for the
   same reason.
2. The service-role key is already available to Next.js routes and never reaches
   the browser. Reuse this pattern; do not invent a second one.

Sign-in itself is `signInWithPassword` **called directly from the browser**
(`login/page.tsx:99`). The session lands in the browser the instant the password
is right — this single fact is what makes true 2FA non-trivial.

### Session verification (backend)
`backend/app/auth/jwt.py` validates the Supabase JWT via JWKS. It is a pure
consumer of whatever Supabase issued and needs **no changes** in this phase.

---

## Part 2 — Is this necessary?

The four flows are not equally justified.

| Flow | Verdict | Why |
|---|---|---|
| Signup confirm | **Worth doing** | Real reliability win: survives cross-browser opens and link-eating scanners. Low cost — Supabase-native. |
| Password reset | **Worth doing** | Removes the "invalid or expired" dead end, which is mostly cross-browser, not real expiry. Low cost — Supabase-native. |
| Password change (signed in) | **Worth doing, highest security value of the three** | Closes a genuine hole: today a stolen session silently becomes permanent account takeover. |
| Login 2FA | **Chosen by the project owner over the recommendation below** | Proceeding as asked. |

**On login 2FA specifically.** The reservation, recorded once so the trade-off is
explicit:

- Email is already the password-reset channel. Whoever controls the inbox can
  reset the password *and* read the code, so both factors reduce to one. It
  raises the bar against a leaked-password attacker, not a compromised-inbox one.
- Supabase has **no native email second factor**. Its MFA API is TOTP only.
  Everything in Stage B is custom code Supabase would otherwise have owned,
  tested and rate-limited.
- TOTP would be stronger *and* natively supported
  (`supabase.auth.mfa.enroll/challenge/verify`), at less code than Stage B.

Stage B is therefore isolated so it can be deferred or swapped for TOTP without
touching Stage A.

---

## Part 3 — Prerequisite that blocks everything

**Custom SMTP must be configured before any of this ships.** Supabase's built-in
email service is rate-limited to a handful of messages per hour and is not for
production — the login page already has a bespoke "try again in about an hour"
message for it. Adding a code to *every* login multiplies email volume.

Configure a provider (Resend, Postmark or SendGrid) in Supabase → Project
Settings → Auth → SMTP. Dashboard configuration, not code, but it gates the phase.

---

## Part 4 — Stage A: codes on signup, reset and password change

All three are **Supabase-native**. No new table, mailer, code generation or crypto.

### A1. Email templates (Supabase dashboard, no code)
In Auth → Email Templates, add `{{ .Token }}` to **Confirm signup**, **Magic
Link**, **Reset password** and **Change email**, keeping `{{ .ConfirmationURL }}`.
Code and link then arrive in one email, so nothing already sitting in an inbox
breaks.

### A2. Shared code-entry component
New `frontend/src/components/auth/otp-field.tsx` — 6-digit input with paste
support, `inputMode="numeric"`, `autoComplete="one-time-code"` (enables OS
autofill from the mail app), and a resend button with a cooldown. Model the
disabled/cooldown behaviour on the existing `forgot: idle | sending | sent` guard
at `login/page.tsx:50` — that guard exists because double-taps trip Supabase's
email rate limit, and the same hazard applies here.

### A3. Signup
`signup/page.tsx`: replace the terminal "Check your inbox" text with the code
field. Call the API already in use at `auth/confirm/route.ts:39`, but with
`token` instead of `token_hash`:

```ts
supabase.auth.verifyOtp({ email, token, type: "signup" })
```

Success returns a session → push to `/dashboard`. Keep the already-registered
branch untouched.

### A4. Password reset
In `login/page.tsx` `handleForgot`: after `resetPasswordForEmail` succeeds, move
to a code step rather than only toasting. Verify with `type: "recovery"`, which
returns a recovery session, then reuse `SetPasswordForm` exactly as
`auth/reset-password/page.tsx` does today.

Keep `/auth/reset-password` working for link-clickers — both routes converge on
the same form.

### A5. Password change while signed in
`settings/profile/page.tsx`: gate `SetPasswordForm` behind a code. Send with
`auth.reauthenticate()` — Supabase's purpose-built call for exactly this, which
emails a nonce to the signed-in user — then pass the code as `nonce` to
`updateUser({ password, nonce })`. No new endpoint needed.

### A6. Point the link at the robust route
Change `emailRedirectTo` / `redirectTo` from `/auth/callback` to `/auth/confirm`
so link-clickers get the cross-browser-safe `verifyOtp` path instead of PKCE.
Small change, removes a real class of "expired link" reports. Leave
`/auth/callback` in place — OAuth still needs it.

---

## Part 5 — Stage B: login 2FA (password + emailed code)

**The core problem:** `signInWithPassword` runs in the browser and returns a
session immediately. To withhold it, sign-in must move server-side.

**Why not the cheap trick:** it is tempting to verify the password, then call
`signInWithOtp` and let Supabase mail the code. Do not. `signInWithOtp` is
callable by anyone holding the public anon key, so enabling it hands every
attacker a *passwordless* login path with only the email address — precisely what
this feature exists to prevent. The code must be ours.

### B1. Migration `0019_login_challenges.sql`

```
login_challenges(
  id uuid pk, user_id uuid, email citext,
  code_hash text,              -- sha256(code + per-row salt); never the code
  expires_at timestamptz,      -- now() + 10 min
  attempts int default 0,      -- hard fail at 5
  consumed_at timestamptz,
  created_at timestamptz, request_ip text
)
```

Index `(email, created_at desc)` for throttling and `(expires_at)` for the sweep.
RLS: deny all — service-role access only, matching the `auth_methods_for_email`
posture in 0017.

### B2. Routes (Next.js, **not** FastAPI — see the sleeping-backend constraint)

- `POST /api/auth/login` — body `{ email, password }`. Verifies the password with
  `signInWithPassword` using the **anon** key, then immediately `signOut()`s that
  throwaway session so nothing is left holding a token. Inserts a challenge,
  emails the code, returns `{ challenge_id }` and **never a session**.
  Rate-limit per email and per IP, reusing the limiter shape already in
  `api/auth/methods/route.ts:19`.
- `POST /api/auth/login/verify` — body `{ challenge_id, code }`. Constant-time
  compare, checks expiry and attempt count, marks consumed, then mints the
  session **without the password**:

  ```ts
  const { data } = await admin.auth.admin.generateLink({ type: "magiclink", email })
  const { data: session } = await supabase.auth.verifyOtp({
    token_hash: data.properties.hashed_token, type: "magiclink",
  })
  ```

  Returns the session; the client adopts it with `supabase.auth.setSession(...)`.
  This is the key move: no password and no access token is ever parked at rest
  waiting for the code.

### B3. Mailer
New `frontend/src/lib/mail.ts` wrapping the chosen provider's HTTP API (Resend is
the least ceremony). One `sendLoginCode(email, code)` function. Same provider as
the SMTP in Part 3, so there is one vendor to manage.

### B4. Login page
Add a `code` step after `password` in the existing three-step machine
(`step: "email" | "password" | "oauth"` at `login/page.tsx:40`). `handleLogin`
posts to `/api/auth/login` instead of calling Supabase directly. Reuse the
`OtpField` from A2 and the existing `emailChip` back-affordance.

### B5. Do not break OAuth
Google/GitHub sign-in must bypass this entirely — the provider already did the
authenticating and `/auth/callback` returns a session directly. Only the password
path gets the second factor.

### B6. Expiry sweep
Delete consumed and expired rows on the existing maintenance schedule. The
backend already runs a maintenance thread on `maintenance_interval_seconds`
(`backend/app/config.py:118`) that prunes `query_logs`, `usage_events` and
expired semantic-cache rows — add this table to that sweep rather than inventing
a second scheduler.

---

## Files

**Modified**

- `frontend/src/app/(auth)/signup/page.tsx` — code step, `verifyOtp({ type: 'signup' })`
- `frontend/src/app/(auth)/login/page.tsx` — reset-code step (A4) and 2FA `code` step (B4)
- `frontend/src/app/(dashboard)/settings/profile/page.tsx` — `reauthenticate()` + `nonce`
- `frontend/src/app/auth/reset-password/page.tsx` — keep the link path working alongside codes

**New**

- `frontend/src/components/auth/otp-field.tsx`
- `frontend/src/app/api/auth/login/route.ts`, `frontend/src/app/api/auth/login/verify/route.ts`
- `frontend/src/lib/mail.ts`
- `supabase/migrations/0019_login_challenges.sql`

**Reused, not rewritten**

- `verifyOtp` — already in `auth/confirm/route.ts:39`
- service-role-in-a-Next-route pattern — `api/auth/methods/route.ts`
- SECURITY DEFINER + deny-all RLS migration shape — `0017_auth_methods_rpc.sql`
- `SetPasswordForm` — both reset paths converge on it unchanged
- maintenance sweep — `backend/app/config.py:118`

**Docs (the drift harness will fail otherwise)**

`scripts/check_docs_sync.py` fails the build when the C4 model, `Readme.md`,
`flow.md` and the docs page disagree with the code. Update `oreag_1.c4` (auth
flow view), `flow.md` and the docs auth section in the same change.

---

## Verification

1. **Templates** — send one of each from Supabase's template previewer; confirm
   code *and* link both render.
2. **Signup** — sign up with a real inbox; type the code → lands on `/dashboard`.
   Then click the link from the *same* email in a **different browser** → also
   works (the regression A6 fixes).
3. **Wrong/expired code** — a wrong code must not consume the challenge until 5
   attempts; the 6th must hard-fail. Assert the row's `attempts` column directly.
4. **Password reset** — request, verify by code, set a new password, confirm the
   old one no longer signs in.
5. **Password change** — confirm `updateUser` is **rejected without the nonce**.
   That is the security property; assert the failure, not just the success.
6. **Login 2FA** — the decisive test: `POST /api/auth/login` with correct
   credentials must return **no session and no tokens** in the body. Inspect the
   raw response. Then verify the code and confirm the session works against the
   FastAPI backend (`jwt.py` should accept it unchanged).
7. **Passwordless hole** — confirm `signInWithOtp` from the browser console with
   only an email does **not** yield a session. If it does, email OTP is enabled
   in the Supabase dashboard and Stage B's guarantee is void.
8. **OAuth unaffected** — Google and GitHub sign-in still land straight on
   `/dashboard` with no code step.
9. **Rate limits** — hammer `/api/auth/login` and confirm 429s per-email and
   per-IP before Supabase's own limiter is reached.
10. `npm run build`, `npx tsc --noEmit`, `npx eslint`, and
    `backend/.venv/Scripts/python.exe -m pytest -q` (currently 409 passing) all green.
