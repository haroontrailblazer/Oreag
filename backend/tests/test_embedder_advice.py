"""Which embedding model to default to, given the language of the documents.

The catalog is BYOK: a user may pick any of the 22 models, and Oreag cannot
override that. What it CAN do is pick a sensible default at project creation
and say plainly when a chosen model is measured not to work for the corpus the
user actually uploaded.

The numbers behind the tiers are in research/cross-lingual-rag/10-model-
recommendations.md. The one that motivates the whole module: the current
hardcoded default, `text-embedding-3-small`, scores an IndicCrosslingualSTS
12-language mean of 0.041 WITH NEGATIVE VALUES (en-ta -0.037, en-or -0.123).
It is not a weak choice for a Hindi corpus, it is a broken one, and nothing in
the product says so today.
"""

import pytest

from app.providers import registry
from app.services import embedder_advice


class TestTier:
    """Every catalog model resolves to a tier, and the tiers are honest."""

    def test_openai_small_is_english_mostly(self):
        # The current default. Belebele engQ 62.9, below the usable line.
        assert embedder_advice.tier_for("openai", "text-embedding-3-small") == "english-mostly"

    def test_gemini_embedding_is_strong(self):
        assert embedder_advice.tier_for("gemini", "gemini-embedding-001") == "strong-multilingual"

    def test_minilm_is_english_mostly(self):
        # MTEB(Indic) rank 12/12, cross-lingual STS -6.3 (negative).
        assert (
            embedder_advice.tier_for("sentence_transformers", "all-MiniLM-L6-v2")
            == "english-mostly"
        )

    def test_mistral_is_unknown_not_assumed_good(self):
        # No native cross-lingual number exists from any source. "unknown" must
        # NOT collapse into "usable" - a leap of faith is not a recommendation.
        assert embedder_advice.tier_for("mistral", "mistral-embed") == "unknown"

    def test_unrecognised_model_is_unknown(self):
        # A model this build has never heard of degrades to "unknown" rather
        # than raising: the catalog moves faster than this table.
        assert embedder_advice.tier_for("openai", "text-embedding-9-enormous") == "unknown"

    def test_every_catalog_model_has_a_tier(self):
        """No catalog entry may be missing from the tier table.

        This is the test that keeps the module honest as the catalog grows: a
        model added to registry.py without a tier here would silently be
        recommended-by-omission.
        """
        missing = []
        for provider, entries in registry.CATALOG.get("embedding", {}).items():
            for entry in entries:
                model = entry["model"] if isinstance(entry, dict) else entry
                if embedder_advice.tier_for(provider, model) == "unknown":
                    if not embedder_advice.is_explicitly_unknown(provider, model):
                        missing.append(f"{provider}/{model}")
        assert missing == [], f"catalog models with no tier entry: {missing}"


class TestRecommend:
    """The default model for a new project, chosen from its document language."""

    def test_english_keeps_the_incumbent_default(self):
        """English projects must not change behaviour.

        text-embedding-3-small is english-mostly, which is exactly right for an
        English corpus. Changing it would be an unrelated regression.
        """
        rec = embedder_advice.recommend("English")
        assert (rec.provider, rec.model) == ("openai", "text-embedding-3-small")

    def test_hindi_does_not_get_the_english_default(self):
        rec = embedder_advice.recommend("Hindi")
        assert rec.model != "text-embedding-3-small"

    def test_hindi_gets_a_strong_multilingual_model(self):
        rec = embedder_advice.recommend("Hindi")
        assert embedder_advice.tier_for(rec.provider, rec.model) == "strong-multilingual"

    def test_tamil_gets_a_strong_multilingual_model(self):
        # Tamil is the sharpest case: text-embedding-3-large scores XTREME-UP
        # 6.0 against gemini-embedding-001's 68.6.
        rec = embedder_advice.recommend("Tamil")
        assert embedder_advice.tier_for(rec.provider, rec.model) == "strong-multilingual"

    def test_unrecognised_language_gets_the_multilingual_model(self):
        """An unknown language name must NOT fall back to the English default.

        services/text_search.py maps an unrecognised language to the 'english'
        stemmer, and that is right there: English stemming on an unknown
        language is a near no-op. The same fallback here would be the opposite
        of safe. An unrecognised name is far more likely to be a real language
        this table never enumerated - Kannada, Odia, Sinhala - or a typo of one,
        than to be English, and sending those to text-embedding-3-large means
        XTREME-UP 6.0 instead of 68.6.

        So the fallback is directional: only an EXPLICITLY English name (or no
        name at all) keeps the incumbent. Everything else is assumed to need a
        multilingual model, because that assumption is cheap when wrong and
        expensive when missing.
        """
        rec = embedder_advice.recommend("Klingon")
        assert embedder_advice.tier_for(rec.provider, rec.model) == "strong-multilingual"

    def test_none_falls_back_to_the_incumbent(self):
        rec = embedder_advice.recommend(None)
        assert (rec.provider, rec.model) == ("openai", "text-embedding-3-small")

    @pytest.mark.parametrize(
        "language", ["Hindi", "Tamil", "Bengali", "Telugu", "Arabic", "Thai", "Japanese"]
    )
    def test_recommended_dimension_is_indexable(self, language):
        """A recommendation that cannot be HNSW-indexed is a latency regression.

        retrieval.ANN_DIMENSIONS = {256, 384, 512, 768, 1024, 1536}; 3072 is
        excluded because pgvector's HNSW limit is 2000 for `vector`. Defaulting
        a project to gemini-embedding-001 at its NATIVE 3072 would give great
        recall and an exact scan on every query.
        """
        from app.services.retrieval import ANN_DIMENSIONS

        rec = embedder_advice.recommend(language)
        assert rec.dimensions in ANN_DIMENSIONS

    def test_recommendation_is_a_real_catalog_entry(self):
        """Never recommend a model the user cannot actually select."""
        rec = embedder_advice.recommend("Hindi")
        entries = registry.CATALOG["embedding"][rec.provider]
        models = [e["model"] if isinstance(e, dict) else e for e in entries]
        assert rec.model in models


class TestProjectCreateDefaults:
    """The advice reaches a real project, at the moment the choice is made.

    A recommendation nobody applies is a comment. These pin the wiring: what a
    creation call actually stores when it does and does not name a language.
    """

    def _create(self, **kw):
        from app.schemas import ProjectCreate

        return ProjectCreate(name="p", **kw)

    def test_hindi_project_does_not_get_the_english_default(self):
        body = self._create(document_language="Hindi")
        assert body.embedding_model != "text-embedding-3-small"

    def test_hindi_project_gets_a_strong_multilingual_model(self):
        body = self._create(document_language="Hindi")
        assert (
            embedder_advice.tier_for(body.embedding_provider, body.embedding_model)
            == "strong-multilingual"
        )

    def test_hindi_project_gets_an_indexable_dimension(self):
        """The default must not hand a new project an exact scan on every query."""
        from app.services.retrieval import ANN_DIMENSIONS

        body = self._create(document_language="Hindi")
        assert body.embedding_dimensions in ANN_DIMENSIONS

    def test_no_language_keeps_todays_default(self):
        """The overwhelmingly common call names no language. It must not change."""
        body = self._create()
        assert (body.embedding_provider, body.embedding_model) == (
            "openai",
            "text-embedding-3-small",
        )

    def test_english_keeps_todays_default(self):
        body = self._create(document_language="English")
        assert (body.embedding_provider, body.embedding_model) == (
            "openai",
            "text-embedding-3-small",
        )

    def test_explicit_model_wins_over_the_recommendation(self):
        """BYOK: an explicit choice is never overridden, however bad it is.

        A user who names all-MiniLM-L6-v2 for a Hindi corpus gets it. They get
        a warning too (see TestRiskWarning), but not a silent substitution -
        Oreag does not spend a user's own metered key on a model they did not
        ask for.
        """
        body = self._create(
            document_language="Hindi",
            embedding_provider="sentence_transformers",
            embedding_model="all-MiniLM-L6-v2",
        )
        assert (body.embedding_provider, body.embedding_model) == (
            "sentence_transformers",
            "all-MiniLM-L6-v2",
        )

    def test_explicit_dimensions_win_over_the_recommendation(self):
        body = self._create(document_language="Hindi", embedding_dimensions=768)
        assert body.embedding_dimensions == 768

    def test_document_language_is_stored_not_just_consumed(self):
        """The language must survive onto the project, not vanish into a default.

        text_search.py reads it to pick the stemmer, and the risk warning reads
        it later. A creation call that used it and dropped it would silently
        re-break keyword search.
        """
        body = self._create(document_language="Hindi")
        assert body.document_language == "Hindi"


class TestRiskWarning:
    """Telling a user their chosen model cannot read their documents."""

    def test_english_model_on_devanagari_corpus_is_risky(self):
        assert embedder_advice.is_risky("openai", "text-embedding-3-small", {"devanagari"})

    def test_strong_model_on_devanagari_corpus_is_not_risky(self):
        assert not embedder_advice.is_risky("gemini", "gemini-embedding-001", {"devanagari"})

    def test_english_model_on_latin_corpus_is_not_risky(self):
        # An English-only model on an English corpus is the correct choice, not
        # a warning. scripts() returns the empty set for Latin text.
        assert not embedder_advice.is_risky("openai", "text-embedding-3-small", frozenset())

    def test_unknown_tier_on_non_latin_corpus_is_risky(self):
        """"No evidence" must warn, not reassure.

        mistral-embed has no published Indic number from any source. Silence is
        not a pass.
        """
        assert embedder_advice.is_risky("mistral", "mistral-embed", {"devanagari"})
