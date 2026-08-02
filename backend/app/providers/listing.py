"""Which models can a given API key actually reach?

Fetched ONCE, when the key is saved (see routers/provider_keys.py and migration
0022), never on the /api/models read path. GET /api/models sits on the dashboard
load, so calling 16 vendors there - even behind a TTL cache - buys a cold cache
after every deploy, a stampede across Render's workers, and one slow vendor
delaying the whole page. Doing it at save time puts the cost on an action the
user is already waiting through, and it happens once.

WHAT COMES BACK: a flat SET OF MODEL IDS, not a role split. The static CATALOG
already knows which of its entries are embedding models, so the merge is a
membership test. This is not laziness - it dodges the hardest part of the
problem. OpenAI's /v1/models returns only id/object/created/owned_by with no
capability field whatsoever (a standing, acknowledged gap), so any role split
would be prefix guesswork that silently mis-sorts fine-tunes and new families.

FAIL-OPEN, for the same reason validation.py is: returning None means "no
opinion", and a caller with no opinion shows the full static catalog. The ways
this can legitimately fail are numerous and mostly not the user's fault - a
vendor outage, blocked egress, a restricted OpenAI key that may embed but not
enumerate (401 on /v1/models while working perfectly), or a vendor that serves
no models endpoint at all. Every one of those must leave the picker usable.
"""
import time

import httpx

from .base import ProviderUnavailableError
from .openai_compat import azure_base_url, split_azure_credential
from .registry import COMPAT_BASE_URLS
from .sarvam_provider import SARVAM_BASE_URL

# Per-page socket timeout AND a total wall-clock deadline across all pages.
# httpx has no total-request deadline and its read timeout applies per chunk, so
# a dribbling vendor could otherwise hold the save open for pages x timeout.
PAGE_TIMEOUT = httpx.Timeout(6.0, connect=4.0)
TOTAL_DEADLINE_SECONDS = 12.0
PAGE_CAP = 10

# Vendors whose models list is PUBLIC: it answers the same for any string, so it
# describes the VENDOR and not the key. Recorded, but never allowed to hide a
# model - see key_scoped in the merge.
#
# Verified by an unauthenticated GET against each: openrouter 200 with 337
# models, jina 200 with 29, sarvam 200 with 1. validation.py already had to
# route around openrouter's for the same reason (it probes /auth/key instead,
# because a public /models would 200 for a garbage key) - the two modules must
# not disagree about the same vendor.
#
# Why this matters beyond labelling, from the same measurement: jina's public
# list does NOT contain "jina-embeddings-v3", the one embedding model Oreag
# offers for it. Pruning by a vendor-wide list would therefore have hidden a
# model that works - which is exactly the failure this set exists to prevent.
_PUBLIC_LIST = {"sarvam", "jina", "openrouter"}

# Vendors with no models endpoint at all (404). Nothing to fetch; they keep the
# full static catalog for ever, which is the correct answer for them.
_NO_LISTING = {"voyage", "perplexity"}


class _Deadline:
    def __init__(self, seconds: float):
        self._end = time.monotonic() + seconds

    def expired(self) -> bool:
        return time.monotonic() >= self._end


def _get(url: str, headers=None, params=None):
    """One page. Returns parsed JSON, or None on any failure whatsoever."""
    try:
        response = httpx.get(url, headers=headers, params=params, timeout=PAGE_TIMEOUT)
        if response.status_code >= 400:
            return None
        return response.json()
    except Exception:
        return None


def _ids_from_openai_shape(payload) -> list[str]:
    return [
        row["id"]
        for row in (payload or {}).get("data", [])
        if isinstance(row, dict) and row.get("id")
    ]


def _fetch_openai_compat(url: str, headers: dict) -> list[str] | None:
    """Single-page {"data":[{"id":...}]}. Used by OpenAI and every compat vendor.

    OpenAI's list is NOT paginated - it is a flat data array with no cursor - so
    a pager here would be dead code that invents a contract the vendor lacks.
    """
    payload = _get(url, headers=headers)
    if payload is None:
        return None
    return _ids_from_openai_shape(payload)


def _fetch_anthropic(secret: str) -> list[str] | None:
    """Anthropic paginates and DEFAULTS TO 20 PER PAGE.

    That default is the trap: a single naive GET looks like it works, returns
    the 20 most recent models - which are the ones you would test with - and
    silently truncates everything older. Ask for the maximum and still follow
    has_more.
    """
    deadline = _Deadline(TOTAL_DEADLINE_SECONDS)
    headers = {"x-api-key": secret, "anthropic-version": "2023-06-01"}
    ids: list[str] = []
    after: str | None = None
    for _ in range(PAGE_CAP):
        if deadline.expired():
            break
        params = {"limit": 1000}
        if after:
            params["after_id"] = after
        payload = _get(
            "https://api.anthropic.com/v1/models", headers=headers, params=params
        )
        if payload is None:
            return None if not ids else ids
        ids.extend(_ids_from_openai_shape(payload))
        if not payload.get("has_more"):
            break
        after = payload.get("last_id")
        if not after:
            break
    return ids


def _fetch_gemini(secret: str) -> list[str] | None:
    """Google paginates with nextPageToken; ids arrive as "models/<id>".

    No key-prefix branch here, deliberately. Both "AIza" and "AQ." keys reach
    this same host - see gemini_provider._client for why pattern-matching
    credentials for routing was removed.
    """
    deadline = _Deadline(TOTAL_DEADLINE_SECONDS)
    ids: list[str] = []
    token: str | None = None
    for _ in range(PAGE_CAP):
        if deadline.expired():
            break
        params = {"key": secret, "pageSize": 1000}
        if token:
            params["pageToken"] = token
        payload = _get(
            "https://generativelanguage.googleapis.com/v1beta/models", params=params
        )
        if payload is None:
            return None if not ids else ids
        for row in payload.get("models", []):
            name = (row or {}).get("name") or ""
            if name:
                ids.append(name.removeprefix("models/"))
        token = payload.get("nextPageToken")
        if not token:
            break
    return ids


def fetch_models(provider: str, secret: str) -> dict | None:
    """{"models": [...], "key_scoped": bool}, or None when unknowable.

    None is not an error path - it is the normal answer for a vendor that
    cannot be enumerated, and callers must treat it as "no opinion".
    """
    secret = (secret or "").strip()
    if not secret or provider in _NO_LISTING:
        return None

    if provider == "gemini":
        ids = _fetch_gemini(secret)
    elif provider == "anthropic":
        ids = _fetch_anthropic(secret)
    elif provider == "openai":
        ids = _fetch_openai_compat(
            "https://api.openai.com/v1/models",
            {"Authorization": f"Bearer {secret}"},
        )
    elif provider == "sarvam":
        ids = _fetch_openai_compat(
            f"{SARVAM_BASE_URL}/models", {"Authorization": f"Bearer {secret}"}
        )
    elif provider == "azure":
        try:
            endpoint, key = split_azure_credential(secret)
        except ProviderUnavailableError:
            return None
        ids = _fetch_openai_compat(
            f"{azure_base_url(endpoint)}/models", {"api-key": key}
        )
    elif provider in COMPAT_BASE_URLS:
        ids = _fetch_openai_compat(
            f"{COMPAT_BASE_URLS[provider]}/models",
            {"Authorization": f"Bearer {secret}"},
        )
    else:
        return None

    if not ids:
        # Empty is indistinguishable from "we misread the response", and an
        # empty list is the one value that could hide everything. Refuse it.
        return None
    return {
        "models": sorted(set(ids)),
        "key_scoped": provider not in _PUBLIC_LIST,
    }


def _entry_id(entry) -> str:
    """CATALOG stores embeddings as dicts and LLMs as bare strings."""
    return entry["model"] if isinstance(entry, dict) else entry


def merge_catalog(catalog: dict, listings: dict) -> dict:
    """Static catalog narrowed to what each key can actually reach.

    `listings` maps provider -> the stored models_json (or None). Narrowing only
    ever REMOVES entries the static catalog already had; nothing new is
    invented, so every surviving embedding entry keeps its dimensions and
    dimension_options. That is not a detail - vendors do not report vector
    dimensionality anywhere, and Oreag needs it to size the pgvector column and
    to decide truncate-vs-reembed.

    Four things deliberately do NOT narrow:
      * no listing (never fetched, vendor down, key can't enumerate),
      * a listing from a PUBLIC models endpoint, which describes the vendor
        rather than the key,
      * a role whose entries all vanished - see below,
      * anything at all when the catalog had nothing for that provider.
    """
    merged: dict = {}
    for role, providers in catalog.items():
        merged[role] = {}
        for provider, entries in providers.items():
            listing = listings.get(provider)
            if not listing or not listing.get("key_scoped") or not entries:
                merged[role] = {**merged[role], provider: entries}
                continue
            available = set(listing.get("models") or ())
            kept = [e for e in entries if _entry_id(e) in available]
            # A role wiped out entirely is far more likely to be our parsing or
            # a vendor naming its deployments differently than a genuine "this
            # key can use no embedding model at all". Prefer showing too much
            # over presenting an empty picker with no way forward.
            merged[role][provider] = kept or entries
    return merged
