"""Two-factor enforcement.

These tests pin the SECURITY property, not the happy path: a valid access
token that has not cleared a second factor must be refused by the API itself,
independently of whatever the browser chooses to render. The frontend prompt is
a courtesy; if these tests pass and the UI is bypassed entirely, the account is
still protected.
"""
import uuid

import pytest
from fastapi import HTTPException

from app.auth import jwt as jwt_module
from app.services import mfa


@pytest.fixture(autouse=True)
def _clear_mfa_cache():
    mfa.reset_cache()
    yield
    mfa.reset_cache()


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeSession:
    """Minimal Session stand-in that records how it was used."""

    def __init__(self, value=False, raises: Exception | None = None):
        self._value = value
        self._raises = raises
        self.executed = 0
        self.rolled_back = False

    def execute(self, *_args, **_kwargs):
        self.executed += 1
        if self._raises is not None:
            raise self._raises
        return _FakeResult(self._value)

    def rollback(self):
        self.rolled_back = True


def _creds(token="token"):
    class C:
        credentials = token

    return C()


def _decode(payload):
    """Patch token decoding so these tests exercise the gate, not PyJWT."""

    def fake_decode(*_args, **_kwargs):
        return payload

    return fake_decode


class TestHasVerifiedFactor:
    def test_true_when_the_database_says_so(self):
        db = _FakeSession(value=True)
        assert mfa.has_verified_factor(db, uuid.uuid4()) is True

    def test_false_when_no_factor(self):
        db = _FakeSession(value=False)
        assert mfa.has_verified_factor(db, uuid.uuid4()) is False

    def test_result_is_memoised_per_user(self):
        db = _FakeSession(value=True)
        user = uuid.uuid4()
        mfa.has_verified_factor(db, user)
        mfa.has_verified_factor(db, user)
        mfa.has_verified_factor(db, user)
        assert db.executed == 1, "the probe should be cached, not re-queried"

    def test_a_different_user_is_not_served_the_cached_answer(self):
        db = _FakeSession(value=True)
        mfa.has_verified_factor(db, uuid.uuid4())
        mfa.has_verified_factor(db, uuid.uuid4())
        assert db.executed == 2

    def test_missing_function_fails_open_and_stops_querying(self):
        """An unapplied 0019 must not lock anybody out, and must not retry."""
        db = _FakeSession(raises=Exception('function public.user_has_verified_mfa(uuid) does not exist'))
        assert mfa.has_verified_factor(db, uuid.uuid4()) is False
        assert db.rolled_back, "a failed probe must not leave an aborted transaction"
        before = db.executed
        mfa.has_verified_factor(db, uuid.uuid4())
        assert db.executed == before, "should stop asking once known missing"

    def test_transient_error_fails_open_without_latching(self):
        db = _FakeSession(raises=Exception("connection reset by peer"))
        assert mfa.has_verified_factor(db, uuid.uuid4()) is False
        assert db.rolled_back
        # A blip must NOT permanently disable enforcement, unlike a missing
        # function - so the next call still queries.
        healthy = _FakeSession(value=True)
        assert mfa.has_verified_factor(healthy, uuid.uuid4()) is True


class TestGetCurrentUserGate:
    def _call(
        self,
        monkeypatch,
        *,
        aal,
        has_factor,
        enforce=True,
        # Default to a method that PROVES the mailbox, so every pre-existing
        # test in this class keeps testing the aal2 rule and nothing else.
        amr=({"method": "otp"},),
        require_email=True,
        # The user wants to be challenged unless they say otherwise, so every
        # pre-existing test keeps exercising the aal2 rule.
        prompt_enabled=True,
    ):
        user_id = uuid.uuid4()
        claims = {"sub": str(user_id), "aal": aal}
        if amr is not None:
            claims["amr"] = list(amr)
        monkeypatch.setattr(jwt_module.pyjwt, "decode", _decode(claims))
        monkeypatch.setattr(jwt_module.settings, "jwt_mode", "hs256")
        monkeypatch.setattr(jwt_module.settings, "mfa_enforce_aal2", enforce)
        monkeypatch.setattr(
            jwt_module.settings, "email_verification_required", require_email
        )
        monkeypatch.setattr(
            jwt_module, "has_verified_factor", lambda _db, _uid: has_factor
        )
        monkeypatch.setattr(
            jwt_module, "two_factor_prompt_enabled", lambda _db, _uid: prompt_enabled
        )
        return user_id, jwt_module.get_current_user(_creds(), _FakeSession())

    def test_aal2_passes(self, monkeypatch):
        user_id, result = self._call(monkeypatch, aal="aal2", has_factor=True)
        assert result == user_id

    def test_no_factor_means_aal1_is_fine(self, monkeypatch):
        """aal1 is the CORRECT level for an account without 2FA - provided the
        session proved the mailbox some other way (here, an emailed code)."""
        user_id, result = self._call(monkeypatch, aal="aal1", has_factor=False)
        assert result == user_id

    def test_aal1_with_a_factor_is_refused(self, monkeypatch):
        with pytest.raises(HTTPException) as exc:
            self._call(monkeypatch, aal="aal1", has_factor=True)
        assert exc.value.status_code == 403, "403, not 401 - the session is real"
        assert exc.value.headers.get(jwt_module.MFA_REQUIRED_HEADER) == "1"

    def test_missing_aal_claim_is_treated_as_unverified(self, monkeypatch):
        """An older token with no aal claim must not sail through the gate."""
        with pytest.raises(HTTPException) as exc:
            self._call(monkeypatch, aal=None, has_factor=True)
        assert exc.value.status_code == 403

    def test_kill_switch_disables_the_gate(self, monkeypatch):
        user_id, result = self._call(
            monkeypatch, aal="aal1", has_factor=True, enforce=False
        )
        assert result == user_id

    def test_the_403_is_distinguishable_from_an_expired_session(self, monkeypatch):
        """The header is what stops clients bouncing users into a login loop."""
        with pytest.raises(HTTPException) as exc:
            self._call(monkeypatch, aal="aal1", has_factor=True)
        assert exc.value.status_code != 401
        assert jwt_module.MFA_REQUIRED_HEADER in (exc.value.headers or {})


class TestEmailVerificationGate:
    """An account with NO second factor must still prove control of its inbox.

    A password is a shared secret that leaks in breaches, and an OAuth login
    proves a Google/GitHub account rather than the address on file. Neither
    demonstrates that the person signing in can read the mailbox, so for an
    account with nothing else enrolled the emailed code IS the second step -
    and it is enforced here rather than in the UI, because a client-side prompt
    is skipped by anyone calling the API directly.
    """

    def _call(self, monkeypatch, *, amr, has_factor=False, require_email=True):
        gate = TestGetCurrentUserGate()
        return gate._call(
            monkeypatch,
            aal="aal1",
            has_factor=has_factor,
            amr=amr,
            require_email=require_email,
        )

    def _refused(self, monkeypatch, **kw):
        with pytest.raises(HTTPException) as exc:
            self._call(monkeypatch, **kw)
        return exc.value

    def test_password_alone_is_refused(self, monkeypatch):
        err = self._refused(monkeypatch, amr=[{"method": "password"}])
        assert err.status_code == 403, "403 - the session is real, just unfinished"
        assert err.headers.get(jwt_module.EMAIL_VERIFICATION_HEADER) == "1"

    def test_oauth_alone_is_refused(self, monkeypatch):
        """Google/GitHub prove the provider account, not this address."""
        err = self._refused(monkeypatch, amr=[{"method": "oauth"}])
        assert err.status_code == 403
        assert err.headers.get(jwt_module.EMAIL_VERIFICATION_HEADER) == "1"

    def test_the_two_403s_are_distinguishable(self, monkeypatch):
        """They lead to DIFFERENT pages. Sending someone to the authenticator
        prompt when they have no authenticator is a dead end."""
        err = self._refused(monkeypatch, amr=[{"method": "password"}])
        assert jwt_module.MFA_REQUIRED_HEADER not in (err.headers or {})

    def test_password_plus_emailed_code_passes(self, monkeypatch):
        user_id, result = self._call(
            monkeypatch, amr=[{"method": "password"}, {"method": "otp"}]
        )
        assert result == user_id

    def test_magic_link_passes(self, monkeypatch):
        user_id, result = self._call(monkeypatch, amr=[{"method": "magiclink"}])
        assert result == user_id

    def test_a_passkey_login_is_not_asked_for_a_code(self, monkeypatch):
        """A passkey is possession plus user verification and is
        phishing-resistant - stacking an emailed code on it adds nothing."""
        user_id, result = self._call(monkeypatch, amr=[{"method": "webauthn"}])
        assert result == user_id

    def test_an_account_with_a_factor_is_not_asked_twice(self, monkeypatch):
        """It already cleared a real challenge to reach aal2. Only the aal2
        rule applies there; this gate must not add a second one."""
        gate = TestGetCurrentUserGate()
        user_id, result = gate._call(
            monkeypatch, aal="aal2", has_factor=True, amr=[{"method": "password"}]
        )
        assert result == user_id

    def test_missing_amr_fails_OPEN(self, monkeypatch):
        """The asymmetry that decides the direction: failing open costs one
        skipped email, failing closed locks every user out of the product with
        the remedy behind the same gate."""
        user_id, result = self._call(monkeypatch, amr=None)
        assert result == user_id

    def test_empty_amr_fails_open(self, monkeypatch):
        user_id, result = self._call(monkeypatch, amr=[])
        assert result == user_id

    def test_plain_string_amr_entries_are_understood(self, monkeypatch):
        """Defensive: the claim is documented as objects, but a bare list of
        strings must not read as 'no methods' and silently fail open."""
        err = self._refused(monkeypatch, amr=["password"])
        assert err.status_code == 403

    def test_kill_switch_disables_only_this_gate(self, monkeypatch):
        user_id, result = self._call(
            monkeypatch, amr=[{"method": "password"}], require_email=False
        )
        assert result == user_id


def test_both_auth_headers_are_cors_exposed():
    """A header the browser cannot READ does not exist to the frontend.

    Both 403s are told apart by a header, and CORS hides every response header
    that is not on this list - so a missing entry turns a precise "confirm your
    email" into an unexplained failure, and the user is bounced to login in a
    loop.
    """
    from app.auth.jwt import EMAIL_VERIFICATION_HEADER, MFA_REQUIRED_HEADER
    from app.config import settings

    exposed = {h.strip().lower() for h in settings.cors_expose_headers.split(",")}
    assert MFA_REQUIRED_HEADER.lower() in exposed
    assert EMAIL_VERIFICATION_HEADER.lower() in exposed


class TestTwoFactorPromptPreference:
    """Keeping a factor while switching the sign-in challenge off.

    Supabase gives a factor two states, verified and unverified - there is no
    "keep it but stop asking". So the only way to stop prompting used to be
    `mfa.unenroll()`, which DELETES the TOTP secret and forces a fresh QR scan
    to turn it back on. The preference decouples the two.
    """

    def _gate(self, monkeypatch, **kw):
        return TestGetCurrentUserGate()._call(monkeypatch, **kw)

    def test_prompt_off_lets_an_aal1_session_through(self, monkeypatch):
        user_id, result = self._gate(
            monkeypatch, aal="aal1", has_factor=True, prompt_enabled=False
        )
        assert result == user_id

    def test_prompt_on_still_refuses(self, monkeypatch):
        """The default. Nothing about this feature may weaken the normal case."""
        with pytest.raises(HTTPException) as exc:
            self._gate(
                monkeypatch, aal="aal1", has_factor=True, prompt_enabled=True
            )
        assert exc.value.status_code == 403
        assert exc.value.headers.get(jwt_module.MFA_REQUIRED_HEADER) == "1"

    def test_prompt_off_still_requires_proof_of_the_mailbox(self, monkeypatch):
        """A factor that is never challenged is not protecting anything, so the
        account falls back to the same rule as one with no factor at all -
        otherwise switching the prompt off would be a way to shed BOTH steps."""
        with pytest.raises(HTTPException) as exc:
            self._gate(
                monkeypatch,
                aal="aal1",
                has_factor=True,
                prompt_enabled=False,
                amr=[{"method": "password"}],
            )
        assert exc.value.status_code == 403
        assert exc.value.headers.get(jwt_module.EMAIL_VERIFICATION_HEADER) == "1"

    def test_the_preference_is_read_only_when_a_factor_exists(self, monkeypatch):
        """Ordering matters for cost: the overwhelming majority of accounts have
        no factor, and they must not pay for a second lookup."""
        calls = []
        monkeypatch.setattr(
            jwt_module,
            "two_factor_prompt_enabled",
            lambda _db, _uid: calls.append(1) or True,
        )
        TestGetCurrentUserGate()._call(monkeypatch, aal="aal1", has_factor=False)
        assert calls == [], "queried the preference for an account with no factor"


class TestPreferenceFailsSafe:
    """Every failure path must return 'keep prompting'.

    The value is only ever consulted to decide whether to SKIP enforcement, so
    an unreadable preference must never be the reason a gate opens.
    """

    def test_missing_function_reports_enabled(self, monkeypatch):
        from app.services import mfa as mfa_module

        monkeypatch.setattr(mfa_module, "_prompt_function_missing", False)
        monkeypatch.setattr(mfa_module, "_prompt_cache", {})
        db = _FakeSession(
            raises=Exception('function public.two_factor_prompt_enabled(uuid) does not exist')
        )
        assert mfa_module.two_factor_prompt_enabled(db, uuid.uuid4()) is True

    def test_a_transient_error_reports_enabled(self, monkeypatch):
        from app.services import mfa as mfa_module

        monkeypatch.setattr(mfa_module, "_prompt_function_missing", False)
        monkeypatch.setattr(mfa_module, "_prompt_cache", {})
        db = _FakeSession(raises=Exception("connection reset by peer"))
        assert mfa_module.two_factor_prompt_enabled(db, uuid.uuid4()) is True
        assert db.rolled_back, "a failed lookup must not poison the transaction"

    def test_a_null_result_reports_enabled(self, monkeypatch):
        """No row means the user never turned it off."""
        from app.services import mfa as mfa_module

        monkeypatch.setattr(mfa_module, "_prompt_function_missing", False)
        monkeypatch.setattr(mfa_module, "_prompt_cache", {})
        assert mfa_module.two_factor_prompt_enabled(_FakeSession(value=None), uuid.uuid4()) is True
