"""Prices come from a refreshed feed, not a hand-written dict.

WHY THIS EXISTS

`MODEL_PRICES_USD_PER_MTOK` is, in its own comment, "hand-written and dated",
and `scripts/reconcile_pricing.py` says the quiet part: "there is no test that
can catch it - the table IS the expected value." Measured on 2026-09-08, six of
its 29 entries were wrong (claude-sonnet-5 at 3.00/15.00 against a real
2.00/10.00; grok-4 overstating output ~6x; both deepseek-v4 understating ~4.5x)
and 17 of the catalog's other 27 ids had no price at all, so their spend showed
as nothing.

THE ONE RULE HERE IS PROVIDER SCOPING. The same model id costs different money
on different vendors, and the feed is keyed by vendor. A lookup that matches on
the id alone resolved Together's Llama-3.3-70B to deepinfra's listing - $0.10
against $1.04, an 8x error - and pointed a Fireworks id at Azure. So a miss must
return None and NEVER another vendor's number: the existing rule, that "a
guessed price is a silently wrong invoice, which is strictly worse than an
honest gap", is what these tests mostly pin.
"""
import json

import pytest

from app.providers import pricing


# A slice of the real feed, in its real shape: vendor-prefixed keys, prices per
# TOKEN (not per million), and a `litellm_provider` that is the only reliable
# statement of who is actually selling it.
FEED = {
    "gpt-4o-mini": {
        "litellm_provider": "openai",
        "input_cost_per_token": 1.5e-07,
        "output_cost_per_token": 6e-07,
        "cache_read_input_token_cost": 7.5e-08,
        "mode": "chat",
    },
    "groq/openai/gpt-oss-20b": {
        "litellm_provider": "groq",
        "input_cost_per_token": 7.5e-08,
        "output_cost_per_token": 3e-07,
        "mode": "chat",
    },
    "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo": {
        "litellm_provider": "together_ai",
        "input_cost_per_token": 1.04e-06,
        "output_cost_per_token": 1.04e-06,
        "mode": "chat",
    },
    # The trap: same model id, different vendor, ~10x cheaper.
    "deepinfra/meta-llama/Llama-3.3-70B-Instruct-Turbo": {
        "litellm_provider": "deepinfra",
        "input_cost_per_token": 1e-07,
        "output_cost_per_token": 3.2e-07,
        "mode": "chat",
    },
    "text-embedding-3-small": {
        "litellm_provider": "openai",
        "input_cost_per_token": 2e-08,
        "mode": "embedding",
    },
    "gemini/gemini-embedding-001": {
        "litellm_provider": "gemini",
        "input_cost_per_token": 1.5e-07,
        "mode": "embedding",
    },
    # Priced per token AND per request. The token half alone understates by
    # roughly 8x on a real query, so this must not be treated as priceable.
    "perplexity/sonar": {
        "litellm_provider": "perplexity",
        "input_cost_per_token": 1e-06,
        "output_cost_per_token": 1e-06,
        "search_context_cost_per_query": {"search_context_size_medium": 0.008},
        "mode": "chat",
    },
    "openai/whatever-no-price": {"litellm_provider": "openai", "mode": "chat"},
}


def _padded(payload: dict) -> dict:
    """`is_usable` refuses anything under MIN_ENTRIES, because a short payload
    is a truncated download rather than a price list. These fixtures are small
    on purpose - readable - so pad them past the floor when the SIZE is not
    what is under test."""
    out = dict(payload)
    i = 0
    while len(out) < pricing.MIN_ENTRIES:
        out[f"openai/filler-{i}"] = {
            "litellm_provider": "openai",
            "input_cost_per_token": 1e-07,
            "output_cost_per_token": 1e-07,
        }
        i += 1
    return out


@pytest.fixture()
def table():
    return pricing.build_table(FEED)


class TestProviderScoping:
    """The defect that made this a subsystem rather than a dict update."""

    def test_the_same_id_resolves_differently_per_vendor(self, table):
        together = table.lookup("meta-llama/Llama-3.3-70B-Instruct-Turbo", "together")
        assert together is not None
        assert (together.input, together.output) == (1.04, 1.04)

    def test_a_vendor_we_do_not_buy_from_is_never_borrowed(self, table):
        """deepinfra lists the same id at a tenth of the price. Oreag has no
        deepinfra provider, so the answer is None - not deepinfra's number."""
        assert table.lookup("meta-llama/Llama-3.3-70B-Instruct-Turbo", "deepinfra") is None

    def test_a_vendor_prefixed_key_matches_a_bare_catalog_id(self, table):
        entry = table.lookup("openai/gpt-oss-20b", "groq")
        assert entry is not None and entry.input == 0.075

    def test_the_free_local_twin_of_a_paid_id_stays_unpriced(self, table):
        """`openai/gpt-oss-20b` is served by groq (paid) AND lmstudio (free)
        under one id. registry.py leaves it unpriced for exactly that reason;
        provider scoping is what lets groq be priced without pricing lmstudio.
        """
        assert table.lookup("openai/gpt-oss-20b", "lmstudio") is None

    def test_an_unknown_provider_gets_nothing(self, table):
        assert table.lookup("gpt-4o-mini", "not-a-provider") is None

    def test_an_entry_with_no_price_is_not_a_price(self, table):
        assert table.lookup("whatever-no-price", "openai") is None


class TestPerRequestFeesAreNotPriceable:
    def test_a_provider_that_always_searches_is_refused(self, table):
        """Perplexity bills a per-query search fee that dwarfs the tokens -
        $0.008 against ~$0.001. Pricing the token half alone would replace an
        honest gap with a number that is confidently ~8x low, which is the one
        thing the NULL-is-not-zero rule exists to prevent."""
        assert table.lookup("sonar", "perplexity") is None

    def test_a_duplicate_listing_without_the_fee_field_does_not_smuggle_it_in(self):
        """The feed carries BOTH `perplexity/sonar` (with the fee) and
        `perplexity/perplexity/sonar` (without it). A field sniff refused the
        first and priced the second under the same name - which is why the rule
        is keyed on the provider instead."""
        t = pricing.build_table({
            "perplexity/sonar": {
                "litellm_provider": "perplexity",
                "input_cost_per_token": 1e-06, "output_cost_per_token": 1e-06,
                "search_context_cost_per_query": {"search_context_size_medium": 0.008},
            },
            "perplexity/perplexity/sonar": {
                "litellm_provider": "perplexity",
                "input_cost_per_token": 2.5e-07, "output_cost_per_token": 2.5e-06,
            },
        })
        assert t.lookup("sonar", "perplexity") is None

    def test_an_OPTIONAL_fee_does_not_block_pricing(self):
        """Gemini models carry `search_context_cost_per_query` because they CAN
        be grounded. Oreag never enables grounding, so their tokens are the
        whole bill. Refusing them - as a field sniff did - left real spend
        showing as nothing for no reason."""
        t = pricing.build_table({
            "gemini-flash-latest": {
                "litellm_provider": "gemini",
                "input_cost_per_token": 3e-07, "output_cost_per_token": 2.5e-06,
                "search_context_cost_per_query": {"search_context_size_medium": 0.008},
            },
        })
        entry = t.lookup("gemini-flash-latest", "gemini")
        assert entry is not None and entry.input == 0.3


class TestEmbeddings:
    def test_an_embedding_model_is_priced_on_its_input_side(self, table):
        entry = table.lookup("gemini-embedding-001", "gemini")
        assert entry is not None and entry.input == 0.15

    def test_an_embedder_has_no_output_price(self, table):
        entry = table.lookup("text-embedding-3-small", "openai")
        assert entry is not None and entry.output is None


class TestCacheRatesAreCarried:
    def test_a_cached_input_rate_is_kept_even_though_nothing_uses_it_yet(self, table):
        """Carried so the entry is complete when TokenUsage learns to count
        cached tokens. Storing it costs nothing; re-deriving it later would
        mean a second pass over the feed."""
        entry = table.lookup("gpt-4o-mini", "openai")
        assert entry.cached_input == 0.075


class TestValidationGuardsTheSwap:
    """A bad payload must never replace a good table."""

    def test_a_healthy_payload_validates(self):
        assert pricing.is_usable(_padded(FEED)) is True

    def test_a_truncated_payload_is_refused(self):
        assert pricing.is_usable({"gpt-4o-mini": FEED["gpt-4o-mini"]}) is False

    def test_a_payload_whose_anchors_vanished_is_refused(self):
        """Size alone is not health: a full-length file that no longer prices
        gpt-4o-mini is not the file we think it is."""
        missing = _padded({k: v for k, v in FEED.items() if k != "gpt-4o-mini"})
        assert pricing.is_usable(missing) is False

    def test_a_negative_rate_is_refused(self):
        bad = _padded(json.loads(json.dumps(FEED)))
        bad["gpt-4o-mini"]["input_cost_per_token"] = -1.0
        assert pricing.is_usable(bad) is False

    def test_garbage_is_refused_rather_than_raising(self):
        assert pricing.is_usable(None) is False
        assert pricing.is_usable([]) is False
        assert pricing.is_usable({"x": "not a dict"}) is False


class TestRefreshNeverRaises:
    """Same contract as tracing.py: this cannot be why a request fails."""

    def test_a_dead_feed_keeps_the_previous_table(self, monkeypatch, table):
        monkeypatch.setattr(pricing, "_table", table)

        def explode(url, timeout):
            raise OSError("no network")

        monkeypatch.setattr(pricing, "_fetch", explode)
        pricing.refresh()
        assert pricing.current() is table

    def test_a_garbage_payload_keeps_the_previous_table(self, monkeypatch, table):
        monkeypatch.setattr(pricing, "_table", table)
        monkeypatch.setattr(pricing, "_fetch", lambda url, timeout: {"junk": 1})
        pricing.refresh()
        assert pricing.current() is table

    def test_a_good_payload_replaces_it(self, monkeypatch, table):
        monkeypatch.setattr(pricing, "_table", None)
        monkeypatch.setattr(pricing, "_fetch", lambda url, timeout: _padded(FEED))
        pricing.refresh()
        assert pricing.current() is not None
        assert pricing.current().lookup("gpt-4o-mini", "openai").input == 0.15


class TestRegistryPrefersTheFeed:
    """The point of the whole subsystem: a model the hand-written table has
    never heard of gets a real cost, and one it prices WRONGLY gets corrected.
    """

    @pytest.fixture(autouse=True)
    def _feed(self, monkeypatch):
        monkeypatch.setattr(pricing, "_table", pricing.build_table({
            # unpriced in MODEL_PRICES_USD_PER_MTOK
            "xai/grok-3-mini": {
                "litellm_provider": "xai",
                "input_cost_per_token": 1.25e-06,
                "output_cost_per_token": 2.5e-06,
            },
            # priced there, and priced WRONG (ours says 3.00/15.00)
            "claude-sonnet-5": {
                "litellm_provider": "anthropic",
                "input_cost_per_token": 2e-06,
                "output_cost_per_token": 1e-05,
            },
            # an embedder we do not price at all
            "gemini/gemini-embedding-001": {
                "litellm_provider": "gemini",
                "input_cost_per_token": 1.5e-07,
            },
        }))

    def test_a_model_absent_from_our_table_is_now_priced(self):
        from app.providers.base import TokenUsage
        from app.providers.registry import cost_breakdown

        got = cost_breakdown("grok-3-mini", TokenUsage(1_000_000, 0, "grok-3-mini"),
                             provider="xai")
        assert got is not None and got["input"] == 1.25

    def test_the_feed_overrides_a_stale_hand_written_price(self):
        from app.providers.base import TokenUsage
        from app.providers.registry import MODEL_PRICES_USD_PER_MTOK, cost_breakdown

        assert MODEL_PRICES_USD_PER_MTOK["claude-sonnet-5"] == (3.00, 15.00)
        got = cost_breakdown("claude-sonnet-5", TokenUsage(1_000_000, 0, "claude-sonnet-5"),
                             provider="anthropic")
        assert got["input"] == 2.0

    def test_an_unpriced_embedder_is_now_priced(self):
        from app.providers.registry import embedding_cost_for

        assert embedding_cost_for("gemini-embedding-001", 1_000_000,
                                  provider="gemini") == 0.15

    def test_without_a_provider_it_falls_back_to_the_hand_written_table(self):
        """Every existing caller passes no provider until it is threaded
        through. Those must keep working, at today's prices."""
        from app.providers.base import TokenUsage
        from app.providers.registry import cost_breakdown

        got = cost_breakdown("claude-sonnet-5", TokenUsage(1_000_000, 0, "claude-sonnet-5"))
        assert got["input"] == 3.0

    def test_a_model_nobody_prices_is_still_None(self):
        from app.providers.base import TokenUsage
        from app.providers.registry import cost_breakdown

        assert cost_breakdown("sarvam-105b", TokenUsage(10, 1, "sarvam-105b"),
                              provider="sarvam") is None
