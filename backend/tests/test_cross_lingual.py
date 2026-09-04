"""Cross-lingual retrieval: ask in one script, search a corpus in another.

The behaviour under test is a GATE, so most of these assert that it stays
shut. The expensive half (does the embedder actually place a Khmer question
near an English passage) cannot run in CI - it needs a live provider - so what
is pinned here is everything around it: when the gate fires, what is sent, what
is NOT sent, that a failure degrades to the old behaviour, and that the answer
cache notices.
"""
import re
import uuid

import pytest

from app.config import settings
from app.models import Project
from app.services import cross_lingual


# Same shape as tests/test_vector_index.py: a detached Project and a fake
# session. Nothing here needs a database - the gate is decided from a script
# table and one cached read, and every test that would touch the corpus stubs
# corpus_profile directly.


@pytest.fixture
def project():
    return Project(
        id=uuid.uuid4(),
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        content_version=7,
    )


@pytest.fixture
def db_session():
    class _NoDB:
        def execute(self, *_a, **_k):  # pragma: no cover - stubbed out
            raise AssertionError("corpus_profile should have been stubbed")

    return _NoDB()


# ── script detection ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The filing deadline is 30 November.", frozenset()),
        ("Quelle est la date limite de dépôt ?", frozenset()),
        ("¿Cuál es la fecha límite?", frozenset()),
        ("वार्षिक विवरणी कब दाखिल करनी है?", frozenset({"devanagari"})),
        ("ஆண்டு அறிக்கை", frozenset({"tamil"})),
        ("বার্ষিক রিটার্ন", frozenset({"bengali"})),
        ("年度报告的申报截止日期", frozenset({"cjk"})),
        ("年次報告書の提出期限", frozenset({"cjk"})),
        ("연차 보고서", frozenset({"hangul"})),
        ("الإقرار السنوي", frozenset({"arabic"})),
        ("годового отчёта", frozenset({"cyrillic"})),
        ("รายงานประจำปี", frozenset({"thai"})),
        ("ລາຍງານປະຈຳປີ", frozenset({"lao"})),
        ("របាយការណ៍ប្រចាំឆ្នាំ", frozenset({"khmer"})),
        ("နှစ်ပတ်လည်အစီရင်ခံစာ", frozenset({"myanmar"})),
        ("", frozenset()),
    ],
)
def test_scripts_identifies_the_writing_system(text, expected):
    assert cross_lingual.scripts(text) == expected


def test_the_three_scripts_this_feature_exists_for_are_detected():
    """Lao, Khmer and Myanmar were the worst three in the measurement.

    A script missing from the table reads as Latin, the gate never fires, and
    the languages that need this most silently miss out - so their presence is
    asserted by name rather than left to the parametrised sweep above.
    """
    names = {name for name, _ in cross_lingual._SCRIPTS}
    assert {"lao", "khmer", "myanmar"} <= names


def test_a_latin_question_needs_no_llm_call(db_session, project):
    """The common case must not pay for a provider round-trip."""

    def explode():  # pragma: no cover - called = test failed
        raise AssertionError("resolved an LLM for a Latin-script question")

    assert (
        cross_lingual.retrieval_query(
            db_session, project, "When is the annual return due?", llm=explode
        )
        == "When is the annual return due?"
    )


# ── the gate ────────────────────────────────────────────────────────────────


class _StubLLM:
    """Answers both calls the path makes: identify the corpus language, then
    translate into it. `calls` records only the translation."""

    model = "stub/translator"

    def __init__(self, reply="When is the annual return due?", language="English"):
        self.reply = reply
        self.language = language
        self.calls: list[tuple[str, str]] = []
        self.identify_calls = 0

    def generate_with_usage(self, system_prompt, user_prompt):
        from app.providers.base import TokenUsage

        if system_prompt.startswith("Name the human language"):
            self.identify_calls += 1
            return self.language, TokenUsage(prompt_tokens=5, completion_tokens=1)
        self.calls.append((system_prompt, user_prompt))
        return self.reply, TokenUsage(prompt_tokens=11, completion_tokens=7)

    def generate(self, system_prompt, user_prompt):
        return self.generate_with_usage(system_prompt, user_prompt)[0]


KHMER = "តើថ្ងៃផុតកំណត់នៃរបាយការណ៍ប្រចាំឆ្នាំគឺនៅពេលណា?"


@pytest.fixture
def english_corpus(monkeypatch):
    monkeypatch.setattr(
        cross_lingual,
        "corpus_profile",
        lambda db, project: (
            frozenset(),
            "The filing deadline for the annual return is 30 November.",
        ),
    )


@pytest.fixture(autouse=True)
def _clean_caches():
    cross_lingual.reset_caches()
    yield
    cross_lingual.reset_caches()


def test_a_khmer_question_against_an_english_corpus_is_translated(
    db_session, project, english_corpus
):
    llm = _StubLLM()
    out = cross_lingual.retrieval_query(db_session, project, KHMER, llm=llm)
    assert out == "When is the annual return due?"
    assert len(llm.calls) == 1


def test_the_translation_prompt_names_the_target_and_shows_no_corpus_text(
    db_session, project, english_corpus
):
    """MEASURED, and the reason this prompt looks the way it does.

    The first version passed a sample passage and asked for "the same language
    as this reference passage", which avoided having to identify the language
    at all. Against gpt-4o-mini it failed on 24 of 24 cross-lingual queries:
    the model read the sample as CONTENT and ANSWERED the question in the
    user's own language rather than translating it. So the target is named,
    and no corpus text enters the prompt where it can be mistaken for
    something to act on.
    """
    llm = _StubLLM(language="English")
    cross_lingual.retrieval_query(db_session, project, KHMER, llm=llm)
    system, user = llm.calls[0]
    assert "into English" in system
    assert "The filing deadline for the annual return is 30 November." not in system
    assert re.search(r"only the translation", system)
    assert user == KHMER


def test_the_corpus_language_is_identified_once_per_content_version(
    db_session, project, english_corpus
):
    llm = _StubLLM()
    for question in (KHMER, KHMER + " ", KHMER + "  "):
        cross_lingual.retrieval_query(db_session, project, question, llm=llm)
    assert llm.identify_calls == 1
    assert len(llm.calls) == 3


def test_an_unidentifiable_corpus_leaves_the_question_alone(
    db_session, project, english_corpus
):
    """Guessing English here would translate a Tamil question into English for
    a Hindi corpus - worse than doing nothing."""
    llm = _StubLLM(language="I'm sorry, I cannot determine that.")
    assert cross_lingual.retrieval_query(db_session, project, KHMER, llm=llm) == KHMER
    assert llm.calls == []


def test_a_khmer_question_against_a_khmer_corpus_is_left_alone(
    db_session, project, monkeypatch
):
    """The same-language path already works. Translating it to English would
    embed English against Khmer chunks and break what is currently correct."""
    monkeypatch.setattr(
        cross_lingual,
        "corpus_profile",
        lambda db, p: (frozenset({"khmer"}), "របាយការណ៍ប្រចាំឆ្នាំ"),
    )
    llm = _StubLLM()
    assert cross_lingual.retrieval_query(db_session, project, KHMER, llm=llm) == KHMER
    assert llm.calls == []


def test_a_mixed_corpus_containing_the_question_script_is_left_alone(
    db_session, project, monkeypatch
):
    monkeypatch.setattr(
        cross_lingual,
        "corpus_profile",
        lambda db, p: (frozenset({"khmer", "cjk"}), "sample"),
    )
    llm = _StubLLM()
    assert cross_lingual.retrieval_query(db_session, project, KHMER, llm=llm) == KHMER
    assert llm.calls == []


def test_an_empty_corpus_is_left_alone(db_session, project, monkeypatch):
    monkeypatch.setattr(cross_lingual, "corpus_profile", lambda db, p: (frozenset(), ""))
    llm = _StubLLM()
    assert cross_lingual.retrieval_query(db_session, project, KHMER, llm=llm) == KHMER
    assert llm.calls == []


def test_the_kill_switch_restores_the_previous_behaviour(
    db_session, project, english_corpus, monkeypatch
):
    monkeypatch.setattr(settings, "cross_lingual_retrieval_enabled", False)
    llm = _StubLLM()
    assert cross_lingual.retrieval_query(db_session, project, KHMER, llm=llm) == KHMER
    assert llm.calls == []


# ── degradation ─────────────────────────────────────────────────────────────


def test_a_provider_failure_degrades_to_the_question_as_asked(
    db_session, project, english_corpus
):
    class Broken:
        model = "stub/broken"

        def generate_with_usage(self, *_):
            raise RuntimeError("provider down")

    assert cross_lingual.retrieval_query(db_session, project, KHMER, llm=Broken()) == KHMER


def test_an_empty_translation_is_refused(db_session, project, english_corpus):
    assert (
        cross_lingual.retrieval_query(db_session, project, KHMER, llm=_StubLLM("  "))
        == KHMER
    )


def test_a_translation_that_stayed_in_the_asked_script_is_refused(
    db_session, project, english_corpus
):
    """A model that echoed the question, or commented on it in the same
    script, has given us nothing - and embedding its commentary is worse than
    embedding the question."""
    echoed = _StubLLM(KHMER + " ?")
    assert cross_lingual.retrieval_query(db_session, project, KHMER, llm=echoed) == KHMER


def test_a_profiling_failure_degrades_to_the_question_as_asked(db_session, project):
    class BadDB:
        def execute(self, *_a, **_k):
            raise RuntimeError("no connection")

    assert cross_lingual.corpus_profile(BadDB(), project) == (frozenset(), "")
    assert cross_lingual.retrieval_query(BadDB(), project, KHMER) == KHMER


# ── metering, tracing and caching ───────────────────────────────────────────


def test_the_translation_call_is_metered(db_session, project, english_corpus):
    """Every token this product spends is counted. A call made here and not
    reported would be a hole in usage_events that nothing else would reveal."""
    seen = []
    cross_lingual.retrieval_query(
        db_session, project, KHMER, llm=_StubLLM(), on_usage=seen.append
    )
    # Two calls: identify the corpus language, then translate into it.
    assert len(seen) == 2
    assert seen[-1].prompt_tokens == 11
    assert seen[-1].completion_tokens == 7


def test_a_repeated_question_is_translated_once(db_session, project, english_corpus):
    """The agentic loop retrieves per sub-query; without the memo one ask pays
    for several translations."""
    llm = _StubLLM()
    for _ in range(4):
        cross_lingual.retrieval_query(db_session, project, KHMER, llm=llm)
    assert len(llm.calls) == 1


def test_the_llm_factory_is_not_resolved_until_the_gate_fires(
    db_session, project, monkeypatch
):
    monkeypatch.setattr(
        cross_lingual, "corpus_profile", lambda db, p: (frozenset({"khmer"}), "x")
    )
    resolved = []

    def factory():  # pragma: no cover - body reached = test failed
        resolved.append(True)
        return _StubLLM()

    cross_lingual.retrieval_query(db_session, project, KHMER, llm=factory)
    assert resolved == []


def test_a_factory_is_called_when_the_gate_does_fire(
    db_session, project, english_corpus
):
    stub = _StubLLM()
    out = cross_lingual.retrieval_query(db_session, project, KHMER, llm=lambda: stub)
    assert out == "When is the annual return due?"
    assert len(stub.calls) == 1


def test_is_active_costs_no_llm_call(db_session, project, english_corpus):
    assert cross_lingual.is_active(db_session, project, KHMER) is True
    assert cross_lingual.is_active(db_session, project, "When is it due?") is False


def test_the_answer_signature_separates_cross_lingual_questions(
    db_session, project, english_corpus
):
    """A question answered before this feature existed was answered from
    different sources. Only the questions whose retrieval actually changed get
    a new key - a global flag would orphan every project's cache on deploy."""
    from app.services.query import _answer_signature

    plain = _answer_signature(project, db_session, "When is the annual return due?")
    cross = _answer_signature(project, db_session, KHMER)
    assert cross != plain
    assert cross.endswith("x1")
    # The no-argument form still works: lightweight project stand-ins elsewhere
    # in the suite call it with a project alone.
    assert _answer_signature(project) == plain


def test_the_corpus_profile_is_cached_per_content_version(db_session, project):
    calls = []

    class CountingDB:
        def execute(self, *_a, **_k):
            calls.append(True)

            class R:
                @staticmethod
                def scalars():
                    class S:
                        @staticmethod
                        def all():
                            return ["The annual return is due 30 November."]

                    return S()

            return R()

    for _ in range(3):
        cross_lingual.corpus_profile(CountingDB(), project)
    assert len(calls) == 1

    project.content_version = (project.content_version or 0) + 1
    cross_lingual.corpus_profile(CountingDB(), project)
    assert len(calls) == 2


# ── the second gate: only translate when the embedder actually failed ───────


def rows_at(*sims):
    return [{"similarity": s, "content": "x"} for s in sims]


def test_a_strong_first_search_is_left_alone(db_session, project, english_corpus):
    """MEASURED, and the reason this gate exists.

    A Ukrainian question ranked the right passage FIRST as asked and SECOND
    once translated - "vidpovidalnist" (liability) came back as
    "responsibility", which pulls toward a different passage. Where the
    embedder already places the question well, replacing the user's words can
    only lose nuance.
    """
    llm = _StubLLM()
    out = cross_lingual.retrieval_query(
        db_session, project, KHMER, rows=rows_at(0.61, 0.4), llm=llm
    )
    assert out == KHMER
    assert llm.calls == []


def test_a_weak_first_search_is_translated(db_session, project, english_corpus):
    """An embedder with no representation of a language scores EVERY chunk
    near zero, because the query vector points nowhere."""
    llm = _StubLLM()
    out = cross_lingual.retrieval_query(
        db_session, project, KHMER, rows=rows_at(0.08, 0.07, 0.02), llm=llm
    )
    assert out == "When is the annual return due?"
    assert len(llm.calls) == 1


def test_no_rows_at_all_counts_as_weak(db_session, project, english_corpus):
    llm = _StubLLM()
    assert cross_lingual.retrieval_query(
        db_session, project, KHMER, rows=[], llm=llm
    ) != KHMER


def test_omitting_rows_keeps_the_script_only_behaviour(
    db_session, project, english_corpus
):
    """Callers that cannot run a search first must not silently lose the
    feature - they get the previous always-translate gate."""
    llm = _StubLLM()
    assert cross_lingual.retrieval_query(db_session, project, KHMER, llm=llm) != KHMER


def test_unusable_similarities_read_as_weak(db_session, project, english_corpus):
    """None, a string, or True are not measurements. Treating them as a high
    score would silently disable the feature; treating them as weak degrades
    to the behaviour that shipped."""
    for junk in (None, "0.9", True):
        cross_lingual.reset_caches()
        llm = _StubLLM()
        cross_lingual.retrieval_query(
            db_session, project, KHMER,
            rows=[{"similarity": junk, "content": "x"}], llm=llm,
        )
        assert len(llm.calls) == 1, junk


def test_the_floor_is_configurable(db_session, project, english_corpus, monkeypatch):
    monkeypatch.setattr(settings, "cross_lingual_similarity_floor", 0.05)
    llm = _StubLLM()
    # 0.08 clears a floor of 0.05, so nothing is translated.
    assert cross_lingual.retrieval_query(
        db_session, project, KHMER, rows=rows_at(0.08), llm=llm
    ) == KHMER


def test_should_consider_costs_no_model_call(db_session, project, english_corpus):
    assert cross_lingual.should_consider(db_session, project, KHMER) is True
    assert cross_lingual.should_consider(db_session, project, "When is it due?") is False


def test_looks_weak_reads_the_best_row_not_the_first(project):
    assert cross_lingual.looks_weak(rows_at(0.01, 0.02, 0.99)) is False
    assert cross_lingual.looks_weak(rows_at(0.10, 0.09)) is True
