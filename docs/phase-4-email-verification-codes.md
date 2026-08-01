# Phase 4 — Email verification codes + TOTP two-factor

> **Status: planned, not implemented.** Written 2026-08-01. Phase 5 (subscriptions
> & payments) was Phase 4 until this document renumbered it.

## Context

Today every identity-proving step in Oreag is a **clicked link**. Links have
failure modes codes don't: they break when the email is opened in a different
browser from the one that started the flow, corporate mail scanners sometimes
*consume* the one-time token before the human clicks, and on a phone the
app-switch is friction. The reset page already carries a dead-end branch for
exactly this ("This password reset link is invalid or has expired").

This phase does two separable things:

1. **Verification codes** alongside the existing links, everywhere.
2. **Opt-in two-factor** via an authenticator app, as a gate that sits *after*
   whichever way the user got in.

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

**Latent bug:** signup and password reset both point at `/auth/callback` (the
fragile PKCE route), while the robust `/auth/confirm` route exists and nothing
links to it. This is the likely cause of most "expired link" reports.

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

Two architectural facts from that file that constrain the design:

1. It deliberately runs as a **Next.js route, not FastAPI** — its comment says
   so: "always up with this page, so the routing works even when the FastAPI
   backend is asleep."
2. The service-role key is already available to Next.js routes and never reaches
   the browser. Reuse this pattern; do not invent a second one.

Sign-in itself is `signInWithPassword` called from the browser
(`login/page.tsx:99`).

### Session verification (backend)
`backend/app/auth/jwt.py` validates the Supabase JWT via JWKS and returns
`payload["sub"]`. It currently ignores every other claim — including `aal`,
which Part 5 will start enforcing.

---

## Part 2 — The security model

Authentication methods are **layered by strength, not stacked**. This is what
Vercel, GitHub and Google actually do — the strongest method that succeeds ends
the ceremony, and weaker methods pick up a second factor behind them.

```
┌─ passkey ─────────────────────────► session        (1 step, strongest)
│
├─ password ────┐
│               ├─► TOTP gate, if enrolled ─► session
└─ emailed code ┘
   magic link
   OAuth ───────► (provider already did MFA) ─► session
```

**Why a passkey needs no second factor.** A passkey is already two factors:
possession of the device plus a biometric or PIN unlocking it (WebAuthn "user
verification"). It is also **phishing-resistant** — the credential is bound to
the origin, so a lookalike domain cannot use it, which is not true of a TOTP code
a user can be tricked into typing. Asking for TOTP after a passkey adds friction
and no security. Vercel doesn't, and neither should this.

**Why the weaker paths do need a gate.** An emailed code cannot be a second
factor *for an email-based login* — both steps land in the same inbox, so it
collapses to one factor with extra steps. A factor that sits **after** the email
step and isn't email does work: an attacker who owns the inbox passes step 1,
then hits a wall. Password reset doesn't rescue them either, because reset drops
them at the same gate.

**Verified against the installed SDK**, not assumed — `@supabase/auth-js@2.108.1`
exposes:

- `signInWithPasskey()` as a **top-level** method, so passkeys are a primary
  login, not only an MFA factor
- `FactorTypes = ["totp", "phone", "webauthn"]`
- `AMRMethods` including `"mfa/webauthn"` and `"mfa/totp"`
- a `WebAuthnApi` with `register()` / `authenticate()` wrapping the browser
  ceremony, so no `@simplewebauthn/browser` dependency is needed

All of this is native. Nothing in this phase requires a custom credential store.

**This is also why email-code login is safe here.** Offering `signInWithOtp` as
a login option would be dangerous if it were the *only* thing between an
attacker and an account, since anyone holding the public anon key can request a
code for any email. TOTP behind it is what makes the option sound.

**And TOTP is enforceable, not just displayed.** Supabase puts an `aal`
(authenticator assurance level) claim in the JWT. A session that has passed TOTP
is `aal2`; one that hasn't is `aal1`. That means the gate lives in
`backend/app/auth/jwt.py`, not only in the login UI — a tampered frontend cannot
skip it. A hand-rolled email 2FA has no equivalent claim and would be enforceable
only in the page that draws it.

### Is each piece necessary?

| Piece | Verdict |
|---|---|
| Codes on signup | **Yes.** Survives cross-browser opens and link-eating scanners. Supabase-native, near-zero cost. |
| Codes on password reset | **Yes.** Removes the "invalid or expired" dead end, which is mostly cross-browser, not real expiry. |
| Code on password change | **Yes — highest security value of the three.** Today a stolen session becomes permanent account takeover with no re-check. |
| Email code as a login option | **Optional but cheap.** Native; helps users who never set a password (OAuth-only accounts already hit this today). |
| **Passkeys** | **Yes — the highest-value item in this phase.** One tap, no shared secret to steal, phishing-resistant, and it syncs across the user's devices so it doubles as the lockout answer. Native. |
| TOTP 2FA | **Yes, as the fallback gate.** Still needed for anyone signing in by password or emailed code on a device with no passkey. Lower priority once passkeys ship. |

---

## Part 3 — Prerequisite that blocks Stages A and B

**Custom SMTP must be configured first.** Supabase's built-in email service is
rate-limited to a handful of messages per hour and is not for production — the
login page already carries a bespoke "try again in about an hour" message for it.
Adding codes multiplies email volume.

Configure a provider (Resend, Postmark or SendGrid) in Supabase → Project
Settings → Auth → SMTP. Dashboard configuration, not code, but it gates the
email-dependent work. **Stage C (TOTP) has no email dependency** and can ship
first if SMTP is delayed.

---

## Stage A — Codes on signup, reset and password change

All Supabase-native. No new table, mailer, code generation or crypto.

### A1. Email templates (Supabase dashboard, no code)
In Auth → Email Templates, add `{{ .Token }}` to **Confirm signup**, **Magic
Link**, **Reset password** and **Change email**, keeping `{{ .ConfirmationURL }}`.
Code and link then arrive in one email, so nothing already sitting in an inbox
breaks.

### A2. Shared code-entry component
New `frontend/src/components/auth/otp-field.tsx` — 6-digit input with paste
support, `inputMode="numeric"`, `autoComplete="one-time-code"` (enables OS
autofill from the mail app), and a resend button with a cooldown. Model the
cooldown on the existing `forgot: idle | sending | sent` guard at
`login/page.tsx:50` — that guard exists because double-taps trip Supabase's email
rate limit, and the same hazard applies here.

### A3. Signup
`signup/page.tsx`: replace the terminal "Check your inbox" text with the code
field. Call the API already in use at `auth/confirm/route.ts:39`, but with
`token` instead of `token_hash`:

```ts
supabase.auth.verifyOtp({ email, token, type: "signup" })
```

Keep the already-registered branch untouched.

### A4. Password reset
In `login/page.tsx` `handleForgot`: after `resetPasswordForEmail` succeeds, move
to a code step rather than only toasting. Verify with `type: "recovery"`, which
returns a recovery session, then reuse `SetPasswordForm` exactly as
`auth/reset-password/page.tsx` does today. Keep `/auth/reset-password` working
for link-clickers — both routes converge on the same form.

### A5. Password change while signed in
`settings/profile/page.tsx`: gate `SetPasswordForm` behind a code. Send with
`auth.reauthenticate()` — Supabase's purpose-built call for exactly this, which
emails a nonce to the signed-in user — then pass the code as `nonce` to
`updateUser({ password, nonce })`. No new endpoint.

### A6. Point the links at the robust route
Change `emailRedirectTo` / `redirectTo` from `/auth/callback` to `/auth/confirm`
so link-clickers get the cross-browser-safe `verifyOtp` path instead of PKCE.
Leave `/auth/callback` in place — OAuth still needs it.

---

## Stage B — Email code as a login option

Password stays exactly as it is. Add a second way in.

`login/page.tsx`, on the `password` step, add a "Email me a code instead" action:

```ts
supabase.auth.signInWithOtp({ email, shouldCreateUser: false })
// user enters the code
supabase.auth.verifyOtp({ email, token, type: "email" })
```

`shouldCreateUser: false` is load-bearing — without it this silently creates
accounts for unknown addresses and becomes an enumeration and spam vector.

Reuse `OtpField` from A2 and the existing `emailChip` back-affordance. The
`/api/auth/methods` lookup already knows whether the account has a password, so
an OAuth-only user can be offered the code path instead of today's
"Set one via email" workaround.

---

## Stage C — TOTP two-factor

Supabase-native (`supabase.auth.mfa.*`). No new auth infrastructure.

### C1. Enrolment UI
New `frontend/src/components/settings/two-factor-card.tsx`, rendered on
`settings/profile/page.tsx` beside the existing "Change password" card.

```ts
const { data } = await supabase.auth.mfa.enroll({ factorType: 'totp' })
// data.totp.qr_code is an SVG data URI - render it directly
// data.totp.secret is the manual-entry fallback
await supabase.auth.mfa.challenge({ factorId: data.id })
await supabase.auth.mfa.verify({ factorId, challengeId, code })
```

A factor stays `unverified` until the first correct code, so a half-finished
enrolment can never lock anyone out. Disabling calls `mfa.unenroll({ factorId })`
and must itself be gated behind a fresh TOTP code.

### C2. The gate at login
After any successful sign-in, `mfa.getAuthenticatorAssuranceLevel()` returns
`{ currentLevel, nextLevel }`. When `nextLevel === 'aal2'` and
`currentLevel === 'aal1'`, the account has a verified factor and the session
hasn't cleared it — render the TOTP step instead of routing to `/dashboard`.

This is one branch in the existing step machine
(`step: "email" | "password" | "oauth"` at `login/page.tsx:40`), and it fires
identically whether the user arrived by password, code, link or OAuth. When no
factor is enrolled the levels match and nothing is shown — which is the
"if 2FA is off, don't ask" requirement.

### C3. Server-side enforcement — the part that makes it real
Migration `0019_mfa_helpers.sql`: a SECURITY DEFINER function
`user_has_verified_mfa(p_user uuid) returns boolean` reading `auth.mfa_factors`
where `status = 'verified'`. Same shape and same deny-by-default posture as
`auth_methods_for_email` in `0017_auth_methods_rpc.sql`.

`backend/app/auth/jwt.py` then reads the `aal` claim it currently discards: if
the user has a verified factor and `aal != 'aal2'`, reject with **403 and a
distinguishable detail code** (not a bare 401 — the frontend must be able to tell
"finish 2FA" apart from "session expired", or users get bounced to login in a
loop).

Cache `user_has_verified_mfa` per user id with a short TTL rather than querying
per request. The codebase already has this pattern — see
`vector_ann_capability_ttl_seconds` in `backend/app/config.py:170` and the
memoised size probe in `services/retrieval.py`.

### C4. Open decision — lockout recovery
**Supabase TOTP does not ship backup codes.** With C3 enforcing `aal2`
server-side, a lost phone means a total lockout from the API, not just the UI.
This must be answered before C3 ships. Options:

- **Allow a second enrolled factor** (a tablet, a password manager). Cheapest,
  entirely native, no new surface.
- **Own backup codes** — a `mfa_recovery_codes` table of one-way hashes, single
  use. More code, and a second credential to store safely.
- **Support-assisted removal** via `auth.admin.mfa.deleteFactor` behind an
  identity check. No build cost, but it is a manual process and a social-engineering
  target.

Recommended: allow multiple factors now, add backup codes if support load
appears.

---

## Files

**Modified**

- `frontend/src/app/(auth)/signup/page.tsx` — code step (A3)
- `frontend/src/app/(auth)/login/page.tsx` — reset-code step (A4), code login (B), TOTP step (C2)
- `frontend/src/app/(dashboard)/settings/profile/page.tsx` — reauth nonce (A5), 2FA card (C1)
- `frontend/src/app/auth/reset-password/page.tsx` — keep the link path alongside codes
- `backend/app/auth/jwt.py` — read and enforce the `aal` claim (C3)

**New**

- `frontend/src/components/auth/otp-field.tsx`
- `frontend/src/components/settings/two-factor-card.tsx`
- `supabase/migrations/0019_mfa_helpers.sql`

**Reused, not rewritten**

- `verifyOtp` — already in `auth/confirm/route.ts:39`
- SECURITY DEFINER + deny-all RLS migration shape — `0017_auth_methods_rpc.sql`
- `SetPasswordForm` — both reset paths converge on it unchanged
- TTL-cached capability probe pattern — `config.py:170`, `services/retrieval.py`
- `/api/auth/methods` — already reports whether a password exists

**Docs (the drift harness will fail otherwise)**

`scripts/check_docs_sync.py` fails the build when the C4 model, `Readme.md`,
`flow.md` and the docs page disagree with the code. Update `oreag_1.c4` (auth
flow view), `flow.md` and the docs auth section in the same change.

---

## Verification

1. **Templates** — send one of each from Supabase's previewer; confirm code *and*
   link both render.
2. **Signup** — sign up with a real inbox, type the code, land on `/dashboard`.
   Then click the link from the *same* email in a **different browser** → also
   works. That second half is the regression A6 fixes.
3. **Wrong/expired code** — repeated wrong codes must not succeed and must not
   consume the challenge early; confirm Supabase's own attempt limit trips.
4. **Password reset** — request, verify by code, set a new password, confirm the
   old one no longer signs in.
5. **Password change** — confirm `updateUser` is **rejected without the nonce**.
   Assert the failure, not just the success — that is the security property.
6. **Code login** — confirm `signInWithOtp` with an unknown email creates **no
   account** (`shouldCreateUser: false` working).
7. **2FA gate** — enrol TOTP, sign out, sign in by password → TOTP prompt appears.
   Repeat arriving by emailed code, by magic link, and by Google OAuth: the
   prompt must appear in **all four**.
8. **Server-side enforcement** — the decisive test. Take the `aal1` access token
   from a session that has *not* passed TOTP and call the FastAPI backend with it
   directly (curl, bypassing the UI entirely). It must be **403**, with a detail
   the frontend can distinguish from an expired session.
9. **2FA off** — an account with no enrolled factor must see **no** prompt and
   must not be 403'd by C3.
10. **Unenrol** — disabling 2FA must itself require a current code, and afterwards
    an `aal1` token must be accepted again.
11. **Lockout** — whichever C4 option is chosen, actually exercise the recovery
    path end to end before shipping C3.
12. `npm run build`, `npx tsc --noEmit`, `npx eslint`, and
    `backend/.venv/Scripts/python.exe -m pytest -q` (currently 409 passing) all green.
