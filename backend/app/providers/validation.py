"""Live credential check, run once before a BYOK provider key is stored.

Provider keys used to be accepted on sight: the upsert route encrypted whatever
string arrived and reported success, and /api/models switched the whole provider
on the moment a row existed. A typo, a revoked key, or the wrong KIND of
credential entirely (a Google OAuth token where an API key was wanted) all
looked identical to a good key right up until the first query ran - by which
point the failure surfaced as broken search or a stalled re-index, a long way
from the settings page that caused it.

This probes the provider once, at save time, so the error lands on the field
that produced it.

FAIL-OPEN IS THE WHOLE DESIGN. Only an explicit 401/403 - the provider actively
reading the credential and refusing it - rejects a key. A 404, a 5xx, a timeout,
a DNS failure, an unroutable network, or any unexpected exception inside the
probe all mean "could not verify", and the key is stored. Failing closed would
turn a vendor outage, an egress firewall, or simply a vendor that doesn't serve
GET /models into a hard block on saving a perfectly good key. A probe that can
lock people out of their own account is worse than the silent-accept it
replaces, so when in doubt this defers to the user.
"""
import httpx

from ..config import settings
from .base import ProviderUnavailableError
from .gemini_provider import looks_like_api_key
from .openai_compat import azure_base_url, split_azure_credential

# Reused rather than re-listed: a second copy of vendor display names would
# drift the moment a provider is added to one map and not the other.
from .registry import COMPAT_BASE_URLS, _PROVIDER_LABELS
from .sarvam_provider import SARVAM_BASE_URL


class InvalidProviderKeyError(ValueError):
    """The provider read this credential and explicitly refused it."""


# Short: this sits in the user's save request, and a slow vendor must not make
# the settings page feel broken. Anything slower than this is "unverified",
# which is a pass - so a tight bound costs correctness nothing.
PROBE_TIMEOUT = httpx.Timeout(8.0, connect=4.0)

# The statuses that mean "this credential is not valid" on their own.
# Deliberately NOT 404: that means the probe URL was wrong, which is our bug.
_REJECTED = {401, 403}

# ...but two vendors answer a bad key with 400, not 401, and a blanket "400 is
# our bug" would let their keys through unchecked - including Google's, the
# provider this whole check was built for. Verified against the live APIs:
#
#   Google  400 {"error":{"message":"API key not valid. Please pass a valid
#                API key.","details":[{"reason":"API_KEY_INVALID"}]}}
#   xAI     400 {"code":"invalid-argument","error":"Incorrect API key
#                provided. ..."}
#
# So a 400 counts as a refusal only when the body says so in as many words.
# These strings are specific enough that a vendor emitting one in response to a
# model-list request is not doing so about anything other than the key.
_INVALID_KEY_MARKERS = (
    "api_key_invalid",
    "api key not valid",
    "invalid api key",
    "invalid_api_key",
    "incorrect api key",
)

# Providers whose keys cannot be checked cheaply. Listed explicitly, because
# "no probe" and "probe that always passes" are indistinguishable from the
# outside and the second one quietly rots into false confidence. Verified live:
#
#   sarvam, jina  GET /models is PUBLIC - answers 200 for any string
#   voyage        no /models endpoint (404)
#   perplexity    no /models endpoint (404)
#
# The alternative for all four is a billed POST (embeddings / chat), which is
# not a reasonable price for validating a key.
_NO_PROBE = {"sarvam", "jina", "voyage", "perplexity"}

# Most OpenAI-compatible vendors gate GET /models behind the key, which makes it
# the ideal probe - no tokens burned, no model name to guess. Exceptions get an
# explicit path here.
_PROBE_PATHS = {
    # OpenRouter serves /models PUBLICLY: it would answer 200 for a garbage key
    # and the probe would be pure theatre. /auth/key is the key-scoped endpoint.
    "openrouter": "/auth/key",
}

_LABELS = {
    "openai": "OpenAI",
    "gemini": "Google",
    "anthropic": "Anthropic",
    "azure": "Azure OpenAI",
    "sarvam": "Sarvam AI",
    **_PROVIDER_LABELS,
}


def _probe(url: str, headers: dict | None = None, params: dict | None = None):
    """(status, body) of the probe request, or None if it never completed.

    Catches every exception on purpose: this runs inside a save the user is
    waiting on, and no failure of a diagnostic probe should be allowed to fail
    that save. None means "unverified", which callers treat as a pass.

    The body comes back because two vendors report a bad key as 400 and only
    the body distinguishes that from a malformed request.
    """
    try:
        response = httpx.get(
            url, headers=headers, params=params, timeout=PROBE_TIMEOUT
        )
        return response.status_code, response.text
    except Exception:
        return None


def _first_sentence(body: str) -> str:
    """Google's own words, trimmed to something that fits a form field."""
    import json

    try:
        message = json.loads(body)["error"]["message"]
    except Exception:
        message = body
    message = " ".join(str(message).split())
    return message[:200]


def _is_refusal(status: int, body: str) -> bool:
    if status in _REJECTED:
        return True
    return status == 400 and any(
        marker in body.lower() for marker in _INVALID_KEY_MARKERS
    )


def _reject_if_refused(result, provider: str) -> None:
    if result is None:  # unverified - see the fail-open policy above
        return
    status, body = result
    if _is_refusal(status, body):
        label = _LABELS.get(provider, provider)
        raise InvalidProviderKeyError(
            f"{label} rejected this key ({status}). Check it was copied in "
            "full, has not been revoked, and belongs to an account with this "
            "API enabled."
        )


def _validate_gemini(key: str) -> None:
    """Google is the one provider where the common mistake is the credential
    TYPE, not a bad key - so the type check is local and comes first.

    google-genai accepts an API key and nothing else. An OAuth token from
    gcloud, the Gemini CLI or Code Assist, and a service-account JSON, are all
    valid Google credentials that this code path cannot use - and a probe would
    not make that clear, since they come back as an ordinary 401.

    BOTH key prefixes are probed against the same host, because both route to
    the same backend (see gemini_provider._client). This used to skip the probe
    for "AQ." keys on the belief they were Vertex-only - which meant the one
    prefix new users actually get was the one never checked.
    """
    if not looks_like_api_key(key):
        raise InvalidProviderKeyError(
            "That does not look like a Gemini API key. Oreag needs a Gemini "
            "API key from aistudio.google.com/apikey - new ones start with "
            "'AQ.', older ones with 'AIza'. OAuth logins from gcloud, the "
            "Gemini CLI or Code Assist, and service-account JSON files, "
            "cannot be used here."
        )
    result = _probe(
        "https://generativelanguage.googleapis.com/v1beta/models",
        params={"key": key},
    )
    # A disabled API is not a bad key, and telling someone to re-issue a
    # working key would send them in exactly the wrong direction. Google names
    # the project in the body; pass that through so the fix is one click.
    if result is not None and "SERVICE_DISABLED" in result[1]:
        raise InvalidProviderKeyError(
            "This key is valid, but the Generative Language API is not enabled "
            "in its Google Cloud project. Enable it in the Google Cloud "
            "console, wait a minute, and save the key again. "
            f"Google's reply: {_first_sentence(result[1])}"
        )
    _reject_if_refused(result, "gemini")


def _request_for(provider: str, secret: str):
    """(url, headers) to probe, or None when this provider has no usable one."""
    if provider in _NO_PROBE:
        return None
    path = _PROBE_PATHS.get(provider, "/models")
    bearer = {"Authorization": f"Bearer {secret}"}

    if provider == "openai":
        return f"https://api.openai.com/v1{path}", bearer
    if provider == "anthropic":
        return "https://api.anthropic.com/v1/models", {
            "x-api-key": secret,
            # Anthropic 400s without it, which would read as "unverified" and
            # quietly disable the check for every Claude key.
            "anthropic-version": "2023-06-01",
        }
    if provider == "sarvam":
        return f"{SARVAM_BASE_URL}{path}", bearer
    if provider == "azure":
        try:
            endpoint, key = split_azure_credential(secret)
        except ProviderUnavailableError:
            # Malformed "endpoint|key" - nothing to probe. The existing split
            # error already explains this well at use time.
            return None
        return f"{azure_base_url(endpoint)}{path}", {"api-key": key}
    if provider in COMPAT_BASE_URLS:
        return f"{COMPAT_BASE_URLS[provider]}{path}", bearer
    return None


def validate_credential(provider: str, secret: str) -> None:
    """Raise InvalidProviderKeyError if `provider` refuses `secret`.

    Silence means either verified-good or could-not-verify; the two are
    deliberately indistinguishable to callers, because both end in "store it".
    """
    if not settings.provider_key_validation_enabled:
        return
    secret = secret.strip()
    if not secret:
        return
    if provider == "gemini":
        _validate_gemini(secret)
        return
    request = _request_for(provider, secret)
    if request is None:
        return
    url, headers = request
    _reject_if_refused(_probe(url, headers=headers), provider)
