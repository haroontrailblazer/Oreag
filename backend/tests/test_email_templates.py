"""Every auth email must carry the tokens its flow actually needs.

WHY THIS EXISTS: the templates were restyled and shipped WITHOUT
`{{ .Token }}`, while the product had moved to asking people to type a code.
The emails looked right, arrived on time, and carried only a link - so every
code field in the app had nothing to fill it with, and nothing failed loudly.
A missing placeholder renders as empty space, not an error.

The reauthentication template is the interesting one: Supabase issues a bare
nonce for it, with no TokenHash and no ConfirmationURL, so a link there is a
dead href. It is asserted code-ONLY rather than merely "has a code".
"""
import pathlib
import re

TEMPLATES = (
    pathlib.Path(__file__).resolve().parents[2] / "supabase" / "templates"
)

# filename -> (needs a typed code, needs a one-click link, /auth/confirm type)
EXPECTED = {
    "confirm-signup.html": (True, True, "signup"),
    "magic-link.html": (True, True, "magiclink"),
    "reset-password.html": (True, True, "recovery"),
    "email-change.html": (True, True, "email_change"),
    # Bare nonce - no TokenHash exists, so no link can be built.
    "reauthentication.html": (True, False, None),
}


def _body(name: str) -> str:
    """Template with HTML comments stripped.

    Load-bearing: each file's header comment NAMES the tokens it does and does
    not use, so a raw search finds `{{ .TokenHash }}` inside the very sentence
    explaining that reauthentication has none - a test that reads the
    documentation instead of the markup.
    """
    raw = (TEMPLATES / name).read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", raw, flags=re.S)


def test_every_expected_template_exists():
    """Guards the guard: a renamed file would make the rest vacuous."""
    missing = [n for n in EXPECTED if not (TEMPLATES / n).is_file()]
    assert missing == [], f"missing templates: {missing}"


def test_each_template_carries_its_code():
    offenders = [
        name
        for name, (needs_code, _, _) in EXPECTED.items()
        if needs_code and "{{ .Token }}" not in _body(name)
    ]
    assert offenders == [], (
        "templates with no {{ .Token }} placeholder: "
        + ", ".join(sorted(offenders))
        + " - the app asks the user to TYPE this code, and a missing "
        "placeholder renders as empty space rather than failing"
    )


def test_link_templates_use_token_hash_not_confirmation_url():
    """{{ .ConfirmationURL }} routes through Supabase's verify endpoint and
    hands back a PKCE ?code=, which only works in the browser that STARTED the
    flow - request on a laptop, open on a phone, and it dead-ends."""
    for name, (_, needs_link, otp_type) in EXPECTED.items():
        body = _body(name)
        if not needs_link:
            continue
        assert "{{ .TokenHash }}" in body, f"{name} has no token-hash link"
        assert "{{ .ConfirmationURL }}" not in body, (
            f"{name} uses ConfirmationURL - breaks across devices"
        )
        assert f"type={otp_type}" in body, (
            f"{name} must verify as type={otp_type}; the wrong type makes the "
            "link fail for a token that is perfectly valid"
        )


def test_reauthentication_has_no_link_at_all():
    """Supabase issues a bare nonce here. Any href is dead on arrival."""
    body = _body("reauthentication.html")
    assert "{{ .TokenHash }}" not in body
    assert "{{ .ConfirmationURL }}" not in body
    assert "<a href" not in body


def test_links_point_at_a_public_landing_path():
    """Every link target must be reachable WITHOUT a session - the person
    clicking it is by definition not signed in yet."""
    public = (
        TEMPLATES.parents[1] / "frontend" / "src" / "proxy.ts"
    ).read_text(encoding="utf-8")
    for name, (_, needs_link, _) in EXPECTED.items():
        if not needs_link:
            continue
        for target in re.findall(r'href="\{\{ \.SiteURL \}\}(/[^?"]+)', _body(name)):
            assert f'"{target}"' in public, (
                f"{name} links to {target}, which is not in PUBLIC_PATHS - the "
                "middleware would bounce the click to /login"
            )


def test_templates_match_the_generator():
    """The files are generated; a hand edit would be silently overwritten and,
    worse, would drift from the four siblings it was meant to match."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_email_templates",
        TEMPLATES.parents[1] / "scripts" / "build_email_templates.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    stale = [
        name
        for name, tpl in module.TEMPLATES.items()
        if (TEMPLATES / name).read_text(encoding="utf-8") != module.render(tpl)
    ]
    assert stale == [], (
        "edited by hand: "
        + ", ".join(sorted(stale))
        + " - change scripts/build_email_templates.py and re-run it"
    )
