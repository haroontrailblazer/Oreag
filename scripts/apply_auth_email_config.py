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


def desired() -> dict[str, object]:
    out: dict[str, object] = {
        "mailer_otp_length": 6,
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
    wanted = desired()

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

    if not args.apply:
        print(f"\nDry run. Backup written to {BACKUP.name}. Re-run with --apply to write.")
        return 0

    request("PATCH", path, token, changes)
    print(f"\nApplied {len(changes)} setting(s). Undo with --restore.")
    print("Send yourself a password reset to confirm the code arrives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
