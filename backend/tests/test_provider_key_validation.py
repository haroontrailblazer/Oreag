"""Save-time validation of BYOK provider keys.

Two properties carry this feature, and they pull in opposite directions:

  * a credential the provider REFUSES must never reach storage, and
  * a credential we merely FAILED TO CHECK must always reach storage.

The second is the one worth guarding hardest. Failing closed would mean a
vendor outage, a blocked egress route, or a vendor that simply doesn't serve
GET /models becomes an unsaveable key - locking a user out of their own account
over a diagnostic. Every "could not verify" path below therefore asserts a PASS.

Nothing here touches the network: `_probe` is monkeypatched everywhere, and one
test asserts that a probe left unstubbed would still fail open rather than
escape to the internet.
"""
import pytest
from fastapi import HTTPException

from app.providers import validation
from app.providers.validation import (
    InvalidProviderKeyError,
    validate_credential,
)
from app.routers.deps import ensure_valid_provider_key


@pytest.fixture(autouse=True)
def _validation_on(monkeypatch):
    monkeypatch.setattr(
        validation.settings, "provider_key_validation_enabled", True
    )


def _probes(monkeypatch, status, body=""):
    """Stub the network probe with a fixed result; record what it was asked.

    `status=None` stands for a probe that never completed at all.
    """
    calls = []

    def fake(url, headers=None, params=None):
        calls.append({"url": url, "headers": headers or {}, "params": params or {}})
        return None if status is None else (status, body)

    monkeypatch.setattr(validation, "_probe", fake)
    return calls


class TestRejection:
    @pytest.mark.parametrize("status", [401, 403])
    def test_an_explicit_refusal_is_rejected(self, monkeypatch, status):
        _probes(monkeypatch, status)
        with pytest.raises(InvalidProviderKeyError):
            validate_credential("openai", "sk-wrong")

    def test_the_message_names_the_provider(self, monkeypatch):
        """A toast saying only 'invalid key' doesn't say WHICH of 16 keys."""
        _probes(monkeypatch, 401)
        with pytest.raises(InvalidProviderKeyError) as exc:
            validate_credential("groq", "gsk-wrong")
        assert "Groq" in str(exc.value)

    def test_a_good_key_passes(self, monkeypatch):
        _probes(monkeypatch, 200)
        validate_credential("openai", "sk-right")


class TestFailsOpen:
    """Every way a probe can fail to produce a verdict must still save."""

    @pytest.mark.parametrize(
        "status",
        [
            None,  # timeout / DNS / connection refused / unexpected exception
            404,  # vendor doesn't serve this path
            429,  # rate limited, says nothing about validity
            500,  # vendor is having an outage
            503,
        ],
    )
    def test_unverifiable_keys_are_stored(self, monkeypatch, status):
        _probes(monkeypatch, status)
        validate_credential("openai", "sk-maybe-fine")

    def test_a_bare_400_is_treated_as_our_bug_not_a_bad_key(self, monkeypatch):
        """A 400 that says nothing about the key means the probe REQUEST was
        malformed. Rejecting on that would fail a good key over our mistake."""
        _probes(monkeypatch, 400, '{"error":"unsupported parameter"}')
        validate_credential("openai", "sk-probably-fine")

    def test_an_exploding_probe_does_not_break_the_save(self, monkeypatch):
        """_probe swallows everything; assert that contract directly, since a
        raise here would surface as a 500 on a save that should have worked."""

        def boom(*args, **kwargs):
            raise RuntimeError("no network in tests")

        monkeypatch.setattr(validation.httpx, "get", boom)
        assert validation._probe("https://example.invalid/models") is None

    @pytest.mark.parametrize("provider", sorted(validation._NO_PROBE))
    def test_unprobeable_providers_are_never_asked(self, monkeypatch, provider):
        """sarvam/jina serve /models publicly (200 for any string) and
        voyage/perplexity don't serve it at all. Probing them would be either
        false confidence or a guaranteed 404, so they are skipped by name."""
        calls = _probes(monkeypatch, 401)
        validate_credential(provider, "whatever")
        assert calls == []

    def test_unknown_provider_is_not_probed(self, monkeypatch):
        calls = _probes(monkeypatch, 401)
        validate_credential("ollama", "irrelevant")
        assert calls == []

    def test_kill_switch_skips_everything(self, monkeypatch):
        calls = _probes(monkeypatch, 401)
        monkeypatch.setattr(
            validation.settings, "provider_key_validation_enabled", False
        )
        validate_credential("openai", "sk-wrong")
        validate_credential("gemini", "definitely-not-a-gemini-key")
        assert calls == []


class TestGemini:
    """The case that prompted this: a Google credential of the wrong TYPE.

    gcloud / Gemini CLI / Code Assist authenticate by OAuth and service-account
    JSON, none of which google-genai can accept as `api_key`. They fail as a
    plain 401, which reads as "bad key" and sends people off to reissue a key
    that was never the problem.
    """

    @pytest.mark.parametrize(
        "credential",
        [
            "ya29.a0AfB_byC-an-oauth-access-token",
            '{"type": "service_account", "project_id": "x"}',
            "gemini-agent-key",
            "",
        ],
    )
    def test_wrong_credential_type_is_named_as_such(self, monkeypatch, credential):
        calls = _probes(monkeypatch, 200)
        # "" is the clear-the-override signal and never reaches the provider.
        if credential == "":
            validate_credential("gemini", credential)
            assert calls == []
            return
        with pytest.raises(InvalidProviderKeyError) as exc:
            validate_credential("gemini", credential)
        message = str(exc.value)
        assert "AIza" in message and "AQ." in message
        # Caught locally - no point asking Google about a non-key.
        assert calls == []

    def test_ai_studio_key_is_probed(self, monkeypatch):
        calls = _probes(monkeypatch, 200)
        validate_credential("gemini", "AIzaSyExample")
        assert len(calls) == 1
        # The key travels as ?key=, never as a bearer header - the Generative
        # Language API ignores Authorization and would 200 for anyone.
        assert calls[0]["params"]["key"] == "AIzaSyExample"

    def test_a_bad_ai_studio_key_is_rejected(self, monkeypatch):
        """Google answers 400, not 401, for a bad key - captured verbatim from
        the live API. A plain "401/403 only" rule would let every typo'd and
        revoked Gemini key straight through, which is the exact case this
        feature was built for."""
        _probes(
            monkeypatch,
            400,
            '{"error":{"code":400,"message":"API key not valid. Please pass a '
            'valid API key.","status":"INVALID_ARGUMENT","details":[{"reason":'
            '"API_KEY_INVALID"}]}}',
        )
        with pytest.raises(InvalidProviderKeyError):
            validate_credential("gemini", "AIzaRevoked")

    def test_aq_keys_are_probed_like_any_other(self, monkeypatch):
        """Inverted deliberately. This used to skip the probe for AQ. keys on
        the belief they were Vertex-only - so the ONE prefix AI Studio issues
        today was the one prefix never checked."""
        calls = _probes(monkeypatch, 200)
        validate_credential("gemini", "AQ.Ab8example")
        assert len(calls) == 1
        assert calls[0]["params"]["key"] == "AQ.Ab8example"

    def test_a_bad_aq_key_is_rejected(self, monkeypatch):
        _probes(monkeypatch, 403)
        with pytest.raises(InvalidProviderKeyError):
            validate_credential("gemini", "AQ.Ab8revoked")

    def test_disabled_api_is_not_reported_as_a_bad_key(self, monkeypatch):
        """The exact failure that started this: a VALID key whose project has
        the API switched off. Telling the user to re-issue a working key would
        send them in precisely the wrong direction, so this message has to say
        'enable the API', and carry Google's own wording."""
        _probes(
            monkeypatch,
            403,
            '{"error":{"code":403,"message":"Generative Language API has not '
            'been used in project 352711716853 before or it is disabled.",'
            '"status":"PERMISSION_DENIED","details":[{"reason":'
            '"SERVICE_DISABLED"}]}}',
        )
        with pytest.raises(InvalidProviderKeyError) as exc:
            validate_credential("gemini", "AQ.Ab8example")
        message = str(exc.value)
        assert "not enabled" in message
        assert "352711716853" in message  # Google names the project - keep it
        assert "revoked" not in message  # must NOT read as "your key is bad"


class TestProbeShape:
    def test_xai_400_with_a_key_complaint_is_rejected(self, monkeypatch):
        """Second vendor that reports a bad key as 400. Body captured live."""
        _probes(
            monkeypatch,
            400,
            '{"code":"invalid-argument","error":"Incorrect API key provided. '
            'You can obtain an API key from https://console.x.ai."}',
        )
        with pytest.raises(InvalidProviderKeyError):
            validate_credential("xai", "xai-wrong")


    def test_anthropic_sends_its_version_header(self, monkeypatch):
        """Without it Anthropic 400s, which fails open - silently disabling the
        check for every Claude key while looking like it works."""
        calls = _probes(monkeypatch, 200)
        validate_credential("anthropic", "sk-ant-x")
        assert calls[0]["headers"]["anthropic-version"] == "2023-06-01"
        assert calls[0]["headers"]["x-api-key"] == "sk-ant-x"

    def test_openrouter_avoids_its_public_models_endpoint(self, monkeypatch):
        """/models needs no auth there, so probing it would pass any string."""
        calls = _probes(monkeypatch, 200)
        validate_credential("openrouter", "sk-or-x")
        assert calls[0]["url"].endswith("/auth/key")

    def test_compat_providers_use_their_own_base_url(self, monkeypatch):
        calls = _probes(monkeypatch, 200)
        validate_credential("mistral", "m-key")
        assert calls[0]["url"] == "https://api.mistral.ai/v1/models"
        assert calls[0]["headers"]["Authorization"] == "Bearer m-key"

    def test_azure_probes_the_users_own_resource(self, monkeypatch):
        calls = _probes(monkeypatch, 200)
        validate_credential("azure", "https://acme.openai.azure.com|az-key")
        assert calls[0]["url"] == "https://acme.openai.azure.com/openai/v1/models"
        # Azure authenticates with api-key, not a bearer token.
        assert calls[0]["headers"]["api-key"] == "az-key"

    def test_malformed_azure_credential_is_not_probed(self, monkeypatch):
        calls = _probes(monkeypatch, 401)
        validate_credential("azure", "no-endpoint-here")
        assert calls == []


class TestRouterHelper:
    def test_refusal_becomes_a_422(self, monkeypatch):
        _probes(monkeypatch, 401)
        with pytest.raises(HTTPException) as exc:
            ensure_valid_provider_key("openai", "sk-wrong")
        assert exc.value.status_code == 422

    def test_none_means_leave_it_alone(self, monkeypatch):
        """A PATCH that doesn't mention the key must not spend a round trip."""
        calls = _probes(monkeypatch, 401)
        ensure_valid_provider_key("openai", None)
        assert calls == []

    def test_empty_string_means_clear_and_is_not_probed(self, monkeypatch):
        calls = _probes(monkeypatch, 401)
        ensure_valid_provider_key("openai", "")
        assert calls == []
