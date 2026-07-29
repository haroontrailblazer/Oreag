"""CORS origin policy.

Two things are under test:

1. build_origin_regex as a PURE function - no app, no network - so the
   preview-hostname pattern can be attacked directly with the hostnames an
   attacker would actually try to register. That includes the ones it does NOT
   keep out: the pattern is a shape filter over a namespace anyone can register
   in, and the tests say so rather than implying an ownership check it cannot
   make.
2. The middleware decision end to end through TestClient, including the
   regression test for the vulnerability this replaced: no response, preflight
   or simple, may carry Access-Control-Allow-Credentials.
"""
import re

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.main import app, build_origin_regex

PROJECT = "oreag"
SCOPE = "myteam"


def _matcher(project=PROJECT, scope=SCOPE, allow_local=False):
    """Compile the regex the middleware would use. fullmatch mirrors Starlette's
    is_allowed_origin (cors.py), so a test failure here is a real behaviour
    change and not an artifact of how the test matches."""
    pattern = build_origin_regex(project, scope, allow_local)
    assert pattern is not None
    return re.compile(pattern).fullmatch


def _app(origins, project="", scope="", allow_local=True):
    """A minimal app carrying the same middleware configuration as main.py, so
    the toggles can be exercised without re-importing the real app under a
    patched environment."""
    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=build_origin_regex(project, scope, allow_local),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Retry-After"],
    )

    @test_app.get("/ping")
    def ping():
        return {"ok": True}

    return TestClient(test_app)


def _preflight(client, origin, method="POST", headers="authorization"):
    return client.options(
        "/ping",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


class TestOriginRegexBuilder:
    def test_no_pattern_when_previews_and_local_are_both_off(self):
        # Fail-closed default: only CORS_ORIGINS applies. None, not "" - an
        # empty pattern fullmatches the empty string and reads as dead config.
        assert build_origin_regex("", "", allow_local=False) is None

    def test_missing_scope_disables_previews(self):
        # Half-configured must not degrade to a looser pattern.
        assert build_origin_regex(PROJECT, "", allow_local=False) is None
        assert build_origin_regex("", SCOPE, allow_local=False) is None

    def test_local_only_still_builds(self):
        assert build_origin_regex("", "", allow_local=True) is not None

    def test_accepts_deployment_and_branch_previews(self):
        match = _matcher()
        assert match("https://oreag-abc123def-myteam.vercel.app")
        assert match("https://oreag-git-main-myteam.vercel.app")
        # branch slugs contain hyphens
        assert match("https://oreag-git-feat-cors-pinning-myteam.vercel.app")

    def test_rejects_other_vercel_tenants(self):
        match = _matcher()
        for origin in (
            "https://evil.vercel.app",
            "https://vercel.app",
            # right project prefix, someone else's scope
            "https://oreag-abc123def-otherteam.vercel.app",
            # the production alias belongs in CORS_ORIGINS, not the regex
            "https://oreag.vercel.app",
        ):
            assert not match(origin), origin

    def test_a_same_shape_tenant_is_admitted_and_that_is_the_known_limit(self):
        """The honest limit of ANY prefix/suffix pattern over *.vercel.app.

        Nothing here pins hostname OWNERSHIP - it cannot: an attacker registers
        a free Vercel project called "oreag-attacker" under their own team and
        Vercel serves it at a hostname of exactly the allowed shape. So the
        regex is a filter that keeps unrelated origins out, and
        allow_credentials=False is the actual control (pinned by
        test_previews_are_never_paired_with_credentials). Rejecting these
        requires leaving VERCEL_PROJECT / VERCEL_SCOPE empty and enumerating
        preview origins in CORS_ORIGINS, or a custom domain - do that before
        adding any cookie-based auth.
        """
        match = _matcher()
        assert match("https://oreag-attacker-myteam.vercel.app")
        assert match("https://oreag-git-owned-by-evil-myteam.vercel.app")

    def test_rejects_anchor_evasion(self):
        match = _matcher()
        for origin in (
            # suffix attack - would pass an unanchored search
            "https://oreag-abc123def-myteam.vercel.app.evil.com",
            # prefix attack
            "https://evil.com/https://oreag-abc123def-myteam.vercel.app",
            "https://oreag-abc123def-myteam.vercel.app.evil",
            # wrong scheme
            "http://oreag-abc123def-myteam.vercel.app",
            # a port is not part of a Vercel origin
            "https://oreag-abc123def-myteam.vercel.app:8080",
        ):
            assert not match(origin), origin

    def test_settings_values_are_escaped_not_interpreted(self):
        # A metacharacter in the project or scope must stay literal; if re.escape
        # were dropped, ".*" here would match any hostname of the right shape.
        match = _matcher(project="or.*g", scope="my.team")
        assert match("https://or.*g-abc123def-my.team.vercel.app")
        assert not match("https://oreag-abc123def-myXteam.vercel.app")
        assert not match("https://orZZZg-abc123def-my.team.vercel.app")

    def test_local_branch_is_gated_by_the_flag(self):
        allowed = _matcher(allow_local=True)
        assert allowed("http://localhost:3000")
        assert allowed("http://192.168.1.50:3000")
        assert allowed("http://127.0.0.1:8000")
        assert allowed("http://10.0.0.4:3000")
        assert allowed("http://172.16.0.9:3000")
        # public IPs are not private-LAN addresses
        assert not allowed("http://172.32.0.1:3000")
        assert not allowed("http://8.8.8.8:3000")

        denied = _matcher(allow_local=False)
        assert not denied("http://localhost:3000")
        assert not denied("http://192.168.1.50:3000")


class TestCorsMiddlewareDecision:
    def test_preflight_from_a_disallowed_origin_is_refused(self):
        client = _app(["https://oreag.vercel.app"], PROJECT, SCOPE)
        res = _preflight(client, "https://attacker.vercel.app")
        assert res.status_code == 400
        assert "Disallowed CORS origin" in res.text
        # the browser gate is the missing header, not the status code
        assert "access-control-allow-origin" not in res.headers

    def test_preflight_from_an_explicit_origin_is_allowed(self):
        client = _app(["https://oreag.vercel.app"], PROJECT, SCOPE)
        res = _preflight(client, "https://oreag.vercel.app")
        assert res.status_code == 200
        assert res.headers["access-control-allow-origin"] == "https://oreag.vercel.app"
        # allow_headers=["*"] mirrors the request back, so bearer auth survives
        # dropping allow_credentials
        assert "authorization" in res.headers["access-control-allow-headers"].lower()

    def test_preflight_from_a_matching_preview_is_allowed(self):
        client = _app([], PROJECT, SCOPE)
        origin = "https://oreag-git-main-myteam.vercel.app"
        res = _preflight(client, origin)
        assert res.status_code == 200
        assert res.headers["access-control-allow-origin"] == origin

    def test_credentials_are_never_advertised(self):
        # The regression test for the actual vulnerability: an allowed origin
        # must not be handed a credentialed channel.
        client = _app(["https://oreag.vercel.app"], PROJECT, SCOPE)
        allowed = _preflight(client, "https://oreag.vercel.app")
        assert "access-control-allow-credentials" not in allowed.headers

        simple = client.get("/ping", headers={"Origin": "https://oreag.vercel.app"})
        assert simple.status_code == 200
        assert simple.headers["access-control-allow-origin"] == "https://oreag.vercel.app"
        assert "access-control-allow-credentials" not in simple.headers

    def test_retry_after_is_readable_cross_origin(self):
        client = _app(["https://oreag.vercel.app"], PROJECT, SCOPE)
        res = client.get("/ping", headers={"Origin": "https://oreag.vercel.app"})
        assert "Retry-After" in res.headers["access-control-expose-headers"]

    def test_lan_origin_follows_the_local_toggle(self):
        origin = "http://192.168.1.50:3000"
        assert _preflight(_app([], allow_local=True), origin).status_code == 200
        assert _preflight(_app([], allow_local=False), origin).status_code == 400


class TestRealAppCors:
    """The app as actually configured by backend/.env, so a config change that
    breaks local dev or re-opens the wildcard fails here."""

    def test_local_dev_origin_still_works(self):
        client = TestClient(app)
        res = _preflight(client, "http://localhost:3000")
        assert res.status_code == 200
        assert res.headers["access-control-allow-origin"] == "http://localhost:3000"

    def test_arbitrary_vercel_app_is_no_longer_allowed(self):
        client = TestClient(app)
        res = _preflight(client, "https://attacker.vercel.app")
        assert res.status_code == 400
        assert "access-control-allow-origin" not in res.headers

    def test_healthz_never_advertises_credentials(self):
        client = TestClient(app)
        res = client.get("/healthz", headers={"Origin": "http://localhost:3000"})
        assert res.status_code == 200
        assert "access-control-allow-credentials" not in res.headers

    def test_previews_are_never_paired_with_credentials(self):
        """The pairing the preview regex rests on, asserted on the CONFIG and
        not just on a response.

        A shape filter over the shared *.vercel.app namespace admits origins
        nobody here owns (see
        TestOriginRegexBuilder::test_a_same_shape_tenant_is_admitted_and_that_is_the_known_limit),
        which is only harmless while no credentials are advertised. Adding
        cookie auth must fail here - loudly, next to this explanation - rather
        than in production.
        """
        configured = [m for m in app.user_middleware if m.cls is CORSMiddleware]
        assert configured, "the app must configure CORS"
        for middleware in configured:
            assert middleware.kwargs.get("allow_credentials") is False


class TestCredentialsGuard:
    """The dangerous pairing is refused at startup, not merely documented.

    The comment in main.py has always said "do not enable credentials while a
    preview regex is active". assert_credentials_safe makes that an invariant
    the process enforces, so whoever adds cookie auth later cannot ship the
    exploitable combination by ignoring a comment.
    """

    def test_credentials_with_a_preview_pattern_refuses_to_start(self):
        from app.main import assert_credentials_safe

        preview = r"https://oreag-[a-z0-9-]+-my\-team\.vercel\.app"
        with pytest.raises(RuntimeError) as exc:
            assert_credentials_safe(True, preview)
        message = str(exc.value)
        # the error has to tell the operator how to get out of it
        assert "CORS_ALLOW_CREDENTIALS" in message
        assert "VERCEL_PROJECT" in message

    def test_credentials_without_a_preview_pattern_is_allowed(self):
        """Cookie auth is legitimate once previews are gone: an explicit
        CORS_ORIGINS list, or a custom domain, can prove ownership."""
        from app.main import assert_credentials_safe

        assert_credentials_safe(True, None) is None

    def test_preview_pattern_without_credentials_is_allowed(self):
        """Today's shipped configuration."""
        from app.main import assert_credentials_safe

        preview = r"https://oreag-[a-z0-9-]+-my\-team\.vercel\.app"
        assert assert_credentials_safe(False, preview) is None

    def test_neither_is_allowed(self):
        from app.main import assert_credentials_safe

        assert assert_credentials_safe(False, None) is None

    def test_the_shipped_app_satisfies_the_guard(self):
        """Belt and braces: the guard already ran at import (the app object
        exists), but assert it against live settings so a future default flip
        is caught here with a readable message."""
        from app.config import settings
        from app.main import _preview_origin, assert_credentials_safe

        assert_credentials_safe(
            settings.cors_allow_credentials,
            _preview_origin(settings.vercel_project, settings.vercel_scope),
        )
