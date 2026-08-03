#!/usr/bin/env python3
"""Apply Oreag's auth email templates and OTP settings to a Supabase project.

Email templates are PLATFORM config, not rows in your database, so the
service-role key cannot touch them. This uses the Management API, which needs a
Personal Access Token:

    Supabase dashboard -> account menu -> Access Tokens -> Generate new token

Run it with the token in the environment - never on the command line, where it
lands in your shell history:

    # PowerShell
    $env:SUPABASE_ACCESS_TOKEN = "sbp_..."
    python scripts/apply_auth_email_config.py --project nzzcfcwgpkamnxuvkhkh

    # bash
    export SUPABASE_ACCESS_TOKEN=sbp_...
    python scripts/apply_auth_email_config.py --project nzzcfcwgpkamnxuvkhkh

By default it only SHOWS what would change. Add --apply to write.

Every run writes the current config to scripts/.auth-config-backup.json first,
so a bad template is one `--restore` away. That file contains your SMTP
password, so it is gitignored - keep it that way.

WHAT IT SETS
  * the four email templates, each carrying BOTH a {{ .Token }} code and a
    {{ .TokenHash }} link into /auth/confirm
  * OTP length 6, matching NEXT_PUBLIC_OTP_LENGTH and every authenticator app
  * the Phase 5 auth hardening: OTP expiry, minimum password length, required
    password character classes, and re-authentication on password change

IT RATCHETS - IT CANNOT LOOSEN A SETTING
  mailer_otp_exp is min(current, 600) and password_min_length is max(current,
  12), so a re-run can only tighten them. Written as flat targets they would
  have WEAKENED this project: the first run found otp_exp already at 300 and
  was about to raise it to 600, doubling the window a stolen code stays usable.
  A hardening script that can loosen a setting is worse than none, because
  nobody re-reads what it did. Anything already correct is skipped, so a re-run
  on a configured project prints "Already up to date".

NEVER PATCH A SINGLE smtp_* FIELD
  The auth config endpoint does NOT do partial updates of the SMTP block. A
  PATCH carrying only `smtp_admin_email` clears smtp_host, smtp_user,
  smtp_pass and smtp_sender_name with it - which drops the project back to the
  default email provider, and on the free tier that ALSO force-resets all four
  email templates to Supabase's defaults and refuses further template edits.
  Change SMTP in the dashboard, or send the whole block at once. This script
  deliberately touches no smtp_* key.

WHY THE LINK IS NOT {{ .ConfirmationURL }}
  That URL routes through Supabase's own verify endpoint, which hands the app
  back a PKCE ?code= - and PKCE only works in the browser that STARTED the
  flow. Request on a laptop, open on a phone, and it fails. Linking straight to
  /auth/confirm with the token hash uses verifyOtp, which works anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.supabase.com/v1"
BACKUP = Path(__file__).resolve().parent / ".auth-config-backup.json"

CODE_BLOCK = """<p style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
          font-size:32px; font-weight:700; letter-spacing:8px;
          padding:16px 0; margin:0;">{{ .Token }}</p>

<p style="color:#666; font-size:14px;">
  This code expires shortly and can only be used once.
</p>"""

FOOTER = """<hr style="border:none; border-top:1px solid #eee; margin:24px 0;">

<p style="color:#666; font-size:13px;">
  {reassurance}
</p>"""


def template(
    heading: str,
    lead: str,
    otp_type: str,
    next_path: str,
    link_label: str,
    reassurance: str,
) -> str:
    """Build one email.

    `link_label` is per-template on purpose. A generic "continue here" tells
    the reader nothing, and the link text is the part of a link people actually
    read before deciding whether to trust it.
    """
    link = (
        "{{ .SiteURL }}/auth/confirm"
        f"?token_hash={{{{ .TokenHash }}}}&type={otp_type}&next={next_path}"
    )
    return (
        f"<h2>{heading}</h2>\n\n"
        f"<p>{lead}</p>\n\n"
        f"{CODE_BLOCK}\n\n"
        f'<p>Or <a href="{link}">{link_label}</a>.</p>\n\n'
        + FOOTER.format(reassurance=reassurance)
    )


TEMPLATES = {
    "confirmation": {
        "subject": "Confirm your email",
        "content": template(
            "Confirm your email",
            "Enter this code to finish setting up your account:",
            "signup",
            "/dashboard",
            "confirm with one click",
            "Didn't create an Oreag account? You can ignore this email - "
            "nothing is created unless the code or link is used.",
        ),
    },
    "magic_link": {
        "subject": "Your sign-in code",
        "content": template(
            "Your sign-in code",
            "Enter this code to sign in:",
            "magiclink",
            "/dashboard",
            "sign in with one click",
            "Didn't try to sign in? You can ignore this email - your account is "
            "safe, and nothing changes unless the code or link is used.",
        ),
    },
    "recovery": {
        "subject": "Reset your password",
        "content": template(
            "Reset your password",
            "Enter this code to set a new password:",
            "recovery",
            "/auth/reset-password",
            "choose a new password here",
            "Didn't request this? You can ignore this email - your password "
            "won't change, and nobody can sign in with this alone.",
        ),
    },
    "email_change": {
        "subject": "Confirm your new email address",
        "content": template(
            "Confirm your new email address",
            "Enter this code to confirm the change:",
            "email_change",
            "/settings/profile",
            "confirm with one click",
            "Didn't ask to change your email? You can ignore this - the address "
            "on your account stays as it is.",
        ),
    },
}


def request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            # Load-bearing. api.supabase.com sits behind Cloudflare, which
            # blocks urllib's default "Python-urllib/3.x" agent outright -
            # every request comes back 403 "error code: 1010", which reads
            # exactly like a bad token and sends you hunting the wrong bug.
            "User-Agent": "oreag-setup/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise SystemExit(
            f"Management API {exc.code} on {method} {path}\n  {detail}\n"
            "  401/403 usually means the token is wrong, expired, or lacks "
            "access to this project."
        ) from exc


# Supabase accepts only a fixed set of strings here - it is an enum of
# colon-separated character CLASSES, not a free-form rule. Guessing costs three
# rejected requests, so the real value is discovered from the API's own error
# (see character_classes_from_error) and this is only the opening bid.
STRONG_CHARACTER_CLASSES = (
    "abcdefghijklmnopqrstuvwxyz:"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ:"
    "0123456789:"
    "!@#$%^&*()_+-=[]{};'\\:\"|<>?,./`~"
)


def character_classes_from_error(detail: str) -> str | None:
    """Pull the strictest value Supabase says it accepts out of a 4xx body.

    The endpoint answers an invalid password_required_characters with a message
    listing the permitted values. Reading them back beats hardcoding a guess
    that a future Supabase release quietly changes.
    """
    candidates = [
        chunk
        for chunk in re.findall(r"[A-Za-z0-9:!@#$%^&*()_+\-=\[\]{};'\\:\"|<>?,./`~]{20,}", detail)
        if "abcdefghijklmnopqrstuvwxyz" in chunk
    ]
    if not candidates:
        return None
    # Most colons = most required classes = strictest.
    return max(candidates, key=lambda c: c.count(":"))


def desired(current: dict | None = None) -> dict[str, object]:
    """The settings this script owns.

    The two PHASE 5 numbers RATCHET - they only ever tighten. Written as a
    fixed target they would have LOOSENED a live project: `mailer_otp_exp` was
    already 300 here, and a flat "set 600" would have doubled the window a
    stolen code stays usable. A hardening script that can weaken a setting is
    worse than no script, because nobody re-reads what it did.
    """
    current = current or {}
    out: dict[str, object] = {
        "mailer_otp_length": 6,
        # PHASE 5. Ceiling, not a target: at most 10 minutes, and never longer
        # than it already is. The Supabase default is a FULL HOUR (3600), and
        # its own advisor flags anything above one - a code that outlives the
        # session it was meant for is a standing invitation to whoever reaches
        # the inbox later.
        "mailer_otp_exp": min(int(current.get("mailer_otp_exp") or 3600), 600),
        # PHASE 5. Floor, not a target: at least 12, and never shorter than it
        # already is. The browser talks to Supabase DIRECTLY - our backend
        # never sees a password - so this is the only place the length rule is
        # real. frontend/src/lib/password.ts asks for the same 12.
        "password_min_length": max(int(current.get("password_min_length") or 0), 12),
        # Supabase refuses any redirect_to not matched here, silently killing
        # the link. The previous value only allowed localhost:3000/auth/callback,
        # so every emailed link in LOCAL dev - which now points at
        # /auth/confirm - was rejected.
        "uri_allow_list": "https://oreag.vercel.app/**,http://localhost:3000/**",
    }
    for key, tpl in TEMPLATES.items():
        out[f"mailer_subjects_{key}"] = tpl["subject"]
        out[f"mailer_templates_{key}_content"] = tpl["content"]
    return out


def try_patch(path: str, token: str, body: dict) -> str | None:
    """PATCH, returning the error text instead of exiting. None means success."""
    try:
        request("PATCH", path, token, body)
        return None
    except SystemExit as exc:
        return str(exc)


def apply_character_classes(path: str, token: str, apply: bool) -> None:
    """PHASE 5: require character classes server-side, discovering the enum.

    Sent as its OWN PATCH, deliberately. Bundled with the rest, a rejected
    enum value would fail validation for the whole payload and silently take
    the OTP expiry and the minimum length down with it.

    Only ever RELAXES toward what Supabase will accept: if the strict value is
    refused, the accepted list is read back out of the error and reported
    rather than guessed at again.
    """
    if not apply:
        print(
            f"\n  password_required_characters -> {STRONG_CHARACTER_CLASSES!r}"
            "\n  (dry run - not sent)"
        )
        return
    detail = try_patch(path, token, {"password_required_characters": STRONG_CHARACTER_CLASSES})
    if detail is None:
        print("\nApplied password_required_characters (lower+upper+digit+symbol).")
        return
    accepted = character_classes_from_error(detail)
    if accepted and accepted != STRONG_CHARACTER_CLASSES:
        print(f"\nSupabase refused that value; it accepts {accepted!r}. Retrying.")
        if try_patch(path, token, {"password_required_characters": accepted}) is None:
            print("Applied the accepted value instead.")
            return
    print(
        "\nCould NOT set password_required_characters. Nothing else was affected "
        f"- this was its own request.\n  {detail[:300]}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="project ref, e.g. abcdefgh...")
    ap.add_argument("--apply", action="store_true", help="write the changes")
    ap.add_argument("--restore", action="store_true", help="put the backup back")
    args = ap.parse_args()

    token = os.environ.get("SUPABASE_ACCESS_TOKEN", "").strip()
    if not token:
        print(
            "SUPABASE_ACCESS_TOKEN is not set.\n"
            "  Create one at: dashboard -> account -> Access Tokens",
            file=sys.stderr,
        )
        return 2

    path = f"/projects/{args.project}/config/auth"

    if args.restore:
        if not BACKUP.exists():
            print(f"No backup at {BACKUP}", file=sys.stderr)
            return 1
        saved = json.loads(BACKUP.read_text(encoding="utf-8"))
        request("PATCH", path, token, saved)
        print(f"Restored {len(saved)} setting(s) from {BACKUP.name}")
        return 0

    current = request("GET", path, token)
    wanted = desired(current)

    # Back up only the keys we are about to touch - the full config includes
    # the SMTP password and every other auth setting.
    BACKUP.write_text(
        json.dumps({k: current.get(k) for k in wanted}, indent=2),
        encoding="utf-8",
    )

    changes = {k: v for k, v in wanted.items() if current.get(k) != v}
    if not changes:
        print("Already up to date - nothing to change.")
        return 0

    print(f"{len(changes)} setting(s) differ:\n")
    for key in sorted(changes):
        before = current.get(key)
        if isinstance(before, str) and len(before) > 60:
            before = before[:57].replace("\n", " ") + "..."
        print(f"  {key}")
        print(f"      now: {before!r}")
        if key == "mailer_otp_length":
            print(f"      new: {changes[key]!r}")
        else:
            print(f"      new: <{len(str(changes[key]))} chars>")

    # The two hardening settings below were opt-in flags while their risks were
    # unproven. Both risks are now closed by evidence from the live project, so
    # leaving them opt-in only meant a fresh project could be configured, report
    # success, and still be missing them:
    #
    #  * password_required_characters - the danger was a server stricter than
    #    the form, so people satisfy every displayed rule and are refused
    #    anyway. frontend/src/lib/password.ts now asks for the same four
    #    classes, so they agree.
    #  * require_reauthentication - the danger was breaking password reset,
    #    which calls updateUser({password}) from a recovery session with NO
    #    nonce. Read live 2026-08-03: it is already True on this project and
    #    reset works, so recovery sessions are exempt.
    #
    # Both are skipped automatically when already correct, so a re-run is a
    # no-op rather than two redundant writes.
    reauth_ok = current.get("security_update_password_require_reauthentication") is True
    chars_ok = bool(current.get("password_required_characters"))

    if not args.apply:
        print(f"\nDry run. Backup written to {BACKUP.name}. Re-run with --apply to write.")
        if not chars_ok:
            apply_character_classes(path, token, apply=False)
        if not reauth_ok:
            print("\n  security_update_password_require_reauthentication -> True")
            print("  (dry run - not sent)")
        return 0

    request("PATCH", path, token, changes)
    print(f"\nApplied {len(changes)} setting(s). Undo with --restore.")

    if not chars_ok:
        apply_character_classes(path, token, apply=True)

    if not reauth_ok:
        # Its own request, and last, so a failure here cannot strand the
        # settings above - the same reason the character classes are separate.
        detail = try_patch(
            path, token, {"security_update_password_require_reauthentication": True}
        )
        print(
            "\nApplied security_update_password_require_reauthentication."
            "\n  Confirm password reset still works - that flow is the one thing "
            "this setting can break."
            if detail is None
            else f"\nCould not set require_reauthentication:\n  {detail[:300]}"
        )

    print("\nSend yourself a password reset to confirm the code still arrives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
