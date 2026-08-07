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
    def _call(self, monkeypatch, *, aal, has_factor, enforce=True):
        user_id = uuid.uuid4()
        monkeypatch.setattr(
            jwt_module.pyjwt, "decode", _decode({"sub": str(user_id), "aal": aal})
        )
        monkeypatch.setattr(jwt_module.settings, "jwt_mode", "hs256")
        monkeypatch.setattr(jwt_module.settings, "mfa_enforce_aal2", enforce)
        monkeypatch.setattr(
            jwt_module, "has_verified_factor", lambda _db, _uid: has_factor
        )
        return user_id, jwt_module.get_current_user(_creds(), _FakeSession())

    def test_aal2_passes(self, monkeypatch):
        user_id, result = self._call(monkeypatch, aal="aal2", has_factor=True)
        assert result == user_id

    def test_no_factor_means_aal1_is_fine(self, monkeypatch):
        """aal1 is the CORRECT level for an account without 2FA."""
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
