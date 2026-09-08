"""Model prices from a refreshed feed, so the table stops going stale.

WHY THIS EXISTS

`registry.MODEL_PRICES_USD_PER_MTOK` is, in its own words, "hand-written and
dated", and `scripts/reconcile_pricing.py` states the consequence: "there is no
test that can catch it - the table IS the expected value." Measured on
2026-09-08, six of its 29 entries were wrong and 17 of the catalog's other 27
ids had no price at all, so real spend on them displayed as nothing.

A feed fixes both halves at once, and fixes two things the table's own comments
name as unfixable:

  * "gemini-flash-latest / gemini-pro-latest and the mistral *-latest ids are
    rolling aliases - the model (and its price) behind them changes without the
    id changing, so any number pinned here would silently go stale." A feed that
    refreshes tracks the alias; a constant cannot.
  * "openai/gpt-oss-20b is served by BOTH groq (paid) and lmstudio (local,
    free) under one id; with a model-keyed table any price would be wrong for
    one of them." Keying on (provider, id) answers both correctly.

PROVIDER SCOPING IS THE WHOLE DESIGN

The feed is keyed by vendor-prefixed ids and the same model costs different
money on different vendors. A lookup that matched on the id alone resolved
Together's `Llama-3.3-70B-Instruct-Turbo` to deepinfra's listing - $0.10
against $1.04 - and pointed a Fireworks id at Azure. So a lookup that cannot
find the model UNDER THE VENDOR WE ACTUALLY BOUGHT FROM returns None, and never
falls through to another vendor. That is `registry`'s existing rule restated: a
guessed price is a silently wrong invoice, and NULL is an honest gap.

FAIL-OPEN, like tracing.py. Every public function swallows its own exceptions.
A dead feed leaves the previous table in place; a missing table falls through to
the bundled snapshot and then to the hand-written dict, so the worst case is
exactly today's behaviour.
"""
import json
import logging
import pathlib
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Which `litellm_provider` values mean "the vendor this project buys from".
#
# Only vendors Oreag can actually resolve a key for. deepinfra, openai-compatible
# resellers and the rest are deliberately ABSENT: an id we do not sell through
# must not be priceable, because that is precisely how a Together model came to
# be priced at deepinfra's rate.
PROVIDER_ALIASES: dict[str, tuple[str, ...]] = {
    "openai": ("openai",),
    "anthropic": ("anthropic",),
    "gemini": ("gemini", "vertex_ai"),
    "azure": ("azure", "azure_ai"),
    "xai": ("xai",),
    "groq": ("groq",),
    "mistral": ("mistral",),
    "deepseek": ("deepseek",),
    "cohere": ("cohere", "cohere_chat"),
    "together": ("together_ai",),
    "fireworks": ("fireworks_ai",),
    "openrouter": ("openrouter",),
    "voyage": ("voyage",),
    "jina": ("jina_ai",),
    # Local runtimes have no vendor in the feed and no price anywhere, which is
    # correct rather than missing. Mapped to nothing so a lookup returns None
    # and the cost stays NULL instead of borrowing a hosted rate for a model
    # the user is running on their own hardware.
    "ollama": (),
    "lmstudio": (),
    "sentence_transformers": (),
    # Sarvam publishes no price in any source consulted.
    "sarvam": (),
    # Mapped, then refused by UNAVOIDABLE_FEE_PROVIDERS below: every sonar call
    # bills a search fee that dwarfs its tokens, so a token-only price would be
    # confidently ~8x low.
    "perplexity": ("perplexity",),
}

# A payload smaller than this is a truncated download, not a price list. The
# real feed carries ~3800 entries.
MIN_ENTRIES = 50

# Prices that must still resolve for a payload to be believable. If OpenAI's
# cheapest chat model has vanished or moved by an order of magnitude, the file
# is not the file we think it is.
_ANCHORS = (("gpt-4o-mini", "openai", 0.15),)


@dataclass(frozen=True, slots=True)
class PriceEntry:
    """USD per 1M tokens. `output` is None for an embedding model - there is no
    completion side to charge for."""

    input: float
    output: float | None = None
    # Carried but not yet used: nothing counts cached tokens yet (measured as
    # unreachable on current traffic). Storing them now costs nothing and saves
    # a second pass over the feed when TokenUsage learns to.
    cached_input: float | None = None
    cache_write: float | None = None
    source: str = "feed"


def _per_mtok(value) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return round(value * 1_000_000, 6)


# Vendors where a per-request fee is UNAVOIDABLE, so a token-only price is
# systematically and badly wrong.
#
# Perplexity is the whole list: every sonar call runs a search, and the search
# fee dwarfs the tokens - about $0.008 a query against ~$0.001 of tokens. A
# token-only figure would report an eighth of the real bill with total
# confidence, which is worse than reporting nothing.
#
# THIS IS A PROVIDER RULE, NOT A FIELD SNIFF, and the first version got that
# wrong. Sniffing for `search_context_cost_per_query` looked principled and
# silently refused to price `gemini-flash-latest`, `gemini-pro-latest` and
# groq's `gpt-oss-20b` - all of which merely CAN be grounded. Gemini's
# grounding is opt-in and providers/gemini_provider.py never enables it (no
# tools, no google_search anywhere), so for Oreag's traffic those models are
# priced correctly by their tokens alone. "Can charge a fee" and "always
# charges a fee" are different claims, and only the second justifies a refusal.
#
# Removing perplexity from this set means modelling a per-request cost
# component, not deleting the set.
UNAVOIDABLE_FEE_PROVIDERS = frozenset({"perplexity"})


class PriceTable:
    """An immutable (provider, id) -> PriceEntry index over one feed payload."""

    __slots__ = ("_by_provider", "size")

    def __init__(self, by_provider: dict, size: int) -> None:
        self._by_provider = by_provider
        self.size = size

    def lookup(self, model: str, provider: str | None) -> PriceEntry | None:
        """The price for `model` AS SOLD BY `provider`, or None.

        None whenever the vendor is unknown to us, has no entry for this id, or
        prices it in a unit a token table cannot express. Never another
        vendor's number.
        """
        if not model or not provider:
            return None
        entries = self._by_provider.get(provider)
        if not entries:
            return None
        bare = model.split("/")[-1]
        for key in (model, bare):
            found = entries.get(key)
            if found is not None:
                return found
        return None


def build_table(payload: dict) -> PriceTable:
    """Index a raw feed payload by (our provider name, model id).

    One feed entry can be reachable under several ids - the full key
    (`together_ai/meta-llama/...`), the key minus its vendor prefix, and the
    bare tail - because the catalog spells models all three ways. All of them
    are registered, but only ever under the vendor that actually sells it.
    """
    reverse: dict[str, list[str]] = {}
    for ours, theirs in PROVIDER_ALIASES.items():
        for alias in theirs:
            reverse.setdefault(alias, []).append(ours)

    by_provider: dict[str, dict[str, PriceEntry]] = {}
    size = 0
    for key, entry in (payload or {}).items():
        if not isinstance(entry, dict):
            continue
        owners = reverse.get(entry.get("litellm_provider") or "")
        if not owners:
            continue
        if any(owner in UNAVOIDABLE_FEE_PROVIDERS for owner in owners):
            continue
        input_rate = _per_mtok(entry.get("input_cost_per_token"))
        if input_rate is None:
            continue
        price = PriceEntry(
            input=input_rate,
            output=_per_mtok(entry.get("output_cost_per_token")),
            cached_input=_per_mtok(entry.get("cache_read_input_token_cost")),
            cache_write=_per_mtok(entry.get("cache_creation_input_token_cost")),
        )
        size += 1
        # Longest form first so a more specific key is never shadowed.
        names = {key, key.split("/", 1)[-1] if "/" in key else key, key.split("/")[-1]}
        for owner in owners:
            slot = by_provider.setdefault(owner, {})
            for name in names:
                slot.setdefault(name, price)
    return PriceTable(by_provider, size)


def is_usable(payload) -> bool:
    """Whether a payload may replace the live table.

    Guards the swap, not the parse: a truncated download, a negative rate or a
    file whose anchors have moved is rejected and the previous table survives.
    Never raises - a malformed payload is a False, not an exception.
    """
    try:
        if not isinstance(payload, dict) or len(payload) < MIN_ENTRIES:
            return False
        for entry in payload.values():
            if not isinstance(entry, dict):
                return False
            for field in ("input_cost_per_token", "output_cost_per_token"):
                value = entry.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if value < 0:
                        return False
        table = build_table(payload)
        for model, provider, expected in _ANCHORS:
            found = table.lookup(model, provider)
            if found is None or abs(found.input - expected) > expected * 0.5:
                return False
        return True
    except Exception:  # pragma: no cover - defensive
        return False


_table: PriceTable | None = None
_lock = threading.Lock()
_SNAPSHOT = pathlib.Path(__file__).with_name("prices.json")


def current() -> PriceTable | None:
    """The live table, loading the bundled snapshot on first use.

    The snapshot is what makes a cold start correct: a fresh Render boot prices
    everything the last refresh knew, before any network call succeeds.
    """
    global _table
    if _table is None:
        with _lock:
            if _table is None:
                _table = _load_snapshot()
    return _table


def _load_snapshot() -> PriceTable | None:
    try:
        if not _SNAPSHOT.exists():
            return None
        payload = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
        return build_table(payload)
    except Exception:
        logger.warning("Could not read the bundled price snapshot", exc_info=True)
        return None


def _fetch(url: str, timeout: float) -> dict:
    import httpx

    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.json()


def refresh() -> bool:
    """Pull the feed and swap the table in if it validates. Never raises.

    Returns True when the table was replaced, so the caller can log it. A
    failure of any kind leaves the previous table exactly where it was, which
    is why this is safe to call from a background sweep.
    """
    global _table
    from ..config import settings

    if not getattr(settings, "pricing_feed_enabled", True):
        return False
    url = getattr(settings, "pricing_feed_url", "") or ""
    if not url:
        return False
    try:
        payload = _fetch(url, getattr(settings, "pricing_feed_timeout_seconds", 30))
    except Exception:
        logger.warning("Price feed fetch failed; keeping the current table",
                       exc_info=True)
        return False
    if not is_usable(payload):
        logger.warning(
            "Price feed payload failed validation (%s entries); keeping the "
            "current table", len(payload) if isinstance(payload, dict) else "?"
        )
        return False
    table = build_table(payload)
    with _lock:
        _table = table
    logger.info("Price feed refreshed: %d priced models", table.size)
    return True


def lookup(model: str, provider: str | None) -> PriceEntry | None:
    """Convenience wrapper over the live table. None when there is no table."""
    table = current()
    return None if table is None else table.lookup(model, provider)
