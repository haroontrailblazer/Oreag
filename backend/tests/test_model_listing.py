"""Per-key model listing, and the merge that narrows the static catalog.

The failure this feature must never cause is worse than the one it fixes: an
empty or wrongly-pruned picker leaves a user unable to build a project at all,
whereas the status quo merely offers a model that turns out not to work. So most
of what is asserted here is about REFUSING to narrow - on a missing listing, a
public one, a failed fetch, or a role that came back empty.
"""
import pytest

from app.providers import listing
from app.providers.listing import fetch_models, merge_catalog

CATALOG = {
    "embedding": {
        "openai": [
            {"model": "text-embedding-3-small", "dimensions": 1536,
             "dimension_options": [512, 1536]},
            {"model": "text-embedding-3-large", "dimensions": 3072},
        ],
        "gemini": [
            {"model": "text-embedding-004", "dimensions": 768, "deprecated": True},
            {"model": "gemini-embedding-001", "dimensions": 3072,
             "dimension_options": [768, 1536, 3072]},
        ],
        "voyage": [{"model": "voyage-3", "dimensions": 1024}],
    },
    "llm": {
        "openai": ["gpt-4o", "gpt-4o-mini"],
        "gemini": ["gemini-3.5-flash", "gemini-2.5-flash"],
        "anthropic": ["claude-sonnet-5"],
    },
}


def _scoped(*models):
    return {"models": list(models), "key_scoped": True}


class TestMergeNarrows:
    def test_only_reachable_models_survive(self):
        merged = merge_catalog(
            CATALOG, {"gemini": _scoped("gemini-3.5-flash", "gemini-embedding-001")}
        )
        assert merged["llm"]["gemini"] == ["gemini-3.5-flash"]
        assert [e["model"] for e in merged["embedding"]["gemini"]] == [
            "gemini-embedding-001"
        ]

    def test_dimensions_survive_the_merge(self):
        """The whole reason the static catalog cannot simply be replaced: no
        vendor reports vector dimensionality, and Oreag sizes its pgvector
        column from it."""
        merged = merge_catalog(CATALOG, {"gemini": _scoped("gemini-embedding-001")})
        entry = merged["embedding"]["gemini"][0]
        assert entry["dimensions"] == 3072
        assert entry["dimension_options"] == [768, 1536, 3072]

    def test_other_providers_are_untouched(self):
        merged = merge_catalog(CATALOG, {"gemini": _scoped("gemini-3.5-flash")})
        assert merged["llm"]["openai"] == CATALOG["llm"]["openai"]
        assert merged["embedding"]["openai"] == CATALOG["embedding"]["openai"]

    def test_the_static_catalog_is_not_mutated(self):
        """merge runs per request against the module-level CATALOG; mutating it
        would leak one user's entitlements to every other user in the process."""
        merge_catalog(CATALOG, {"gemini": _scoped("gemini-3.5-flash")})
        assert CATALOG["llm"]["gemini"] == ["gemini-3.5-flash", "gemini-2.5-flash"]
        assert len(CATALOG["embedding"]["gemini"]) == 2


class TestMergeRefusesToNarrow:
    def test_no_listing_keeps_everything(self):
        assert merge_catalog(CATALOG, {}) == CATALOG
        assert merge_catalog(CATALOG, {"gemini": None}) == CATALOG

    def test_a_public_list_never_hides_anything(self):
        """sarvam and jina serve /models without auth, so their list describes
        the VENDOR. Pruning by it would hide models the key can really use."""
        public = {"models": ["something-else"], "key_scoped": False}
        merged = merge_catalog(CATALOG, {"gemini": public})
        assert merged["llm"]["gemini"] == CATALOG["llm"]["gemini"]

    def test_a_role_wiped_out_falls_back_to_static(self):
        """A listing naming only chat models must not empty the EMBEDDING
        picker - far likelier a parsing gap than a key that can embed nothing."""
        merged = merge_catalog(CATALOG, {"gemini": _scoped("gemini-3.5-flash")})
        assert merged["llm"]["gemini"] == ["gemini-3.5-flash"]
        assert merged["embedding"]["gemini"] == CATALOG["embedding"]["gemini"]

    def test_an_empty_model_list_cannot_blank_a_picker(self):
        merged = merge_catalog(CATALOG, {"gemini": _scoped()})
        assert merged["llm"]["gemini"] == CATALOG["llm"]["gemini"]

    def test_a_provider_absent_from_the_catalog_is_ignored(self):
        merged = merge_catalog(CATALOG, {"mistral": _scoped("mistral-large")})
        assert merged == CATALOG


class TestDeprecatedModels:
    """Retiring a model must never break a project that already stores it.

    The trap this guards is specific and was caught in review: CATALOG["llm"]
    holds bare strings and validate_llm is a `model not in list` membership
    test, so marking an entry by turning it into a dict would make EVERY model
    of that provider fail validation. Hence a separate set, and hence these
    tests assert resolvability as hard as they assert hiding.
    """

    def test_deprecated_llms_still_validate(self):
        """validate_llm runs on every query. A retired id that stopped
        resolving would 500 an existing project on every single search."""
        from app.providers.registry import DEPRECATED_LLMS, validate_llm

        for provider, models in DEPRECATED_LLMS.items():
            for model in models:
                validate_llm(provider, model)  # must not raise

    def test_deprecated_llms_are_actually_in_the_catalog(self):
        """A typo here would silently mark nothing - the id would never match a
        catalog entry and the model would keep being offered."""
        from app.providers.registry import CATALOG, DEPRECATED_LLMS

        for provider, models in DEPRECATED_LLMS.items():
            listed = CATALOG["llm"].get(provider, [])
            assert listed, f"{provider} has no LLM entries"
            for model in models:
                assert model in listed, f"{provider}/{model} not in the catalog"

    def test_deprecated_embeddings_still_resolve(self):
        from app.providers.registry import CATALOG, resolve_embedding_dimensions

        for provider, entries in CATALOG["embedding"].items():
            for entry in entries:
                if entry.get("deprecated"):
                    assert (
                        resolve_embedding_dimensions(provider, entry["model"])
                        == entry["dimensions"]
                    )

    def test_no_provider_is_left_with_nothing_to_pick(self):
        """The failure that makes a provider unusable rather than merely dated:
        if every entry for a role is retired, the picker is empty and no project
        can be created on it at all."""
        from app.providers.registry import CATALOG, DEPRECATED_LLMS

        for provider, entries in CATALOG["llm"].items():
            live = [m for m in entries if m not in DEPRECATED_LLMS.get(provider, ())]
            assert live, f"every {provider} LLM is deprecated"
        for provider, entries in CATALOG["embedding"].items():
            live = [e for e in entries if not e.get("deprecated")]
            assert live, f"every {provider} embedding model is deprecated"

    def test_the_api_reports_both_roles(self):
        from app.providers.registry import deprecated_model_ids

        reported = deprecated_model_ids()
        assert "gemini-2.5-flash" in reported["llm"]["gemini"]
        assert "text-embedding-004" in reported["embedding"]["gemini"]
        # Providers with nothing retired are omitted, not sent as empty lists.
        assert all(ids for ids in reported["llm"].values())
        assert all(ids for ids in reported["embedding"].values())


class TestStoredListingSurface:
    """What Settings reads to say "N models available" vs "not checked yet"."""

    def _key(self, models_json):
        from app.models import ProviderKey

        return ProviderKey(provider="gemini", models_json=models_json)

    def test_never_fetched_reads_as_unknown_not_zero(self):
        """None and 0 must not collapse: "we never looked" and "this key can
        reach nothing" call for opposite UI, and opposite picker behaviour."""
        assert self._key(None).models_available is None

    def test_counts_the_stored_list(self):
        key = self._key({"models": ["a", "b", "c"], "key_scoped": True})
        assert key.models_available == 3

    def test_a_malformed_row_does_not_raise(self):
        """Serialised by an older build, or hand-edited - a settings page must
        not 500 over it."""
        assert self._key({"key_scoped": True}).models_available == 0


class TestFetchModels:
    def test_gemini_strips_the_models_prefix_and_paginates(self, monkeypatch):
        pages = [
            {"models": [{"name": "models/gemini-3.5-flash"}], "nextPageToken": "t2"},
            {"models": [{"name": "models/gemini-embedding-001"}]},
        ]
        seen = []

        def fake_get(url, headers=None, params=None):
            seen.append(params or {})
            return pages[len(seen) - 1]

        monkeypatch.setattr(listing, "_get", fake_get)
        result = fetch_models("gemini", "AQ.Ab8example")
        assert result["models"] == ["gemini-3.5-flash", "gemini-embedding-001"]
        assert result["key_scoped"] is True
        assert seen[1]["pageToken"] == "t2"

    def test_anthropic_asks_for_a_big_page_and_follows_has_more(self, monkeypatch):
        """The default limit is 20. A single naive GET returns the 20 newest
        models - exactly the ones you would test with - and silently drops the
        rest, so this asserts both the explicit limit and the follow."""
        pages = [
            {"data": [{"id": "claude-sonnet-5"}], "has_more": True, "last_id": "x1"},
            {"data": [{"id": "claude-haiku-4-5"}], "has_more": False},
        ]
        seen = []

        def fake_get(url, headers=None, params=None):
            seen.append(params or {})
            return pages[len(seen) - 1]

        monkeypatch.setattr(listing, "_get", fake_get)
        result = fetch_models("anthropic", "sk-ant-x")
        assert result["models"] == ["claude-haiku-4-5", "claude-sonnet-5"]
        assert seen[0]["limit"] == 1000
        assert seen[1]["after_id"] == "x1"

    @pytest.mark.parametrize("provider", ["sarvam", "jina", "openrouter"])
    def test_public_list_providers_are_flagged_not_scoped(
        self, monkeypatch, provider
    ):
        """All three answer an UNAUTHENTICATED GET /models with 200, so their
        list describes the vendor. openrouter is the easy one to get wrong -
        it is an ordinary compat provider everywhere else in the code."""
        monkeypatch.setattr(
            listing, "_get", lambda *a, **k: {"data": [{"id": "some-model"}]}
        )
        assert fetch_models(provider, "anything")["key_scoped"] is False

    def test_the_two_modules_agree_about_public_lists(self):
        """validation.py already routes around openrouter's public /models by
        probing /auth/key. If one module learns a vendor is public and the
        other does not, the disagreement is silent and shows up as a bogus
        'verified' claim in the UI."""
        from app.providers import validation

        assert set(validation._PROBE_PATHS) <= listing._PUBLIC_LIST

    @pytest.mark.parametrize("provider", ["voyage", "perplexity"])
    def test_providers_without_a_models_endpoint_are_not_called(
        self, monkeypatch, provider
    ):
        calls = []
        monkeypatch.setattr(
            listing, "_get", lambda *a, **k: calls.append(1) or {"data": []}
        )
        assert fetch_models(provider, "key") is None
        assert calls == []

    def test_a_failed_fetch_returns_no_opinion(self, monkeypatch):
        monkeypatch.setattr(listing, "_get", lambda *a, **k: None)
        assert fetch_models("openai", "sk-x") is None

    def test_an_exploding_request_never_escapes(self, monkeypatch):
        """_get is the only place network errors can arise; a raise here would
        turn a working key-save into a 500."""

        def boom(*args, **kwargs):
            raise RuntimeError("no network in tests")

        monkeypatch.setattr(listing.httpx, "get", boom)
        assert listing._get("https://example.invalid/models") is None

    def test_an_empty_response_is_treated_as_unknowable(self, monkeypatch):
        """An empty list is the one value that could hide every model, and it
        is indistinguishable from a response we failed to parse."""
        monkeypatch.setattr(listing, "_get", lambda *a, **k: {"data": []})
        assert fetch_models("openai", "sk-x") is None

    def test_blank_secret_is_not_fetched(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            listing, "_get", lambda *a, **k: calls.append(1) or {"data": []}
        )
        assert fetch_models("openai", "   ") is None
        assert calls == []
