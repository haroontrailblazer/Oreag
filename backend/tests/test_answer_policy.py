"""Migration 0032: per-project answer policy.

Four behaviours here have already been wrong once, or would fail silently:

  * a Latin-only depth classifier disabled the agentic path for every other
    script, and nothing failed - the answer just came back short
  * `is_sufficient` COUNTED strong sources but handed the whole retrieved list
    to the prompt, so a 0.05 chunk was citable as if it supported the claim
  * a new answer-affecting setting that is not in the cache signature keeps
    serving pre-change answers for up to the L2 TTL of 24h
  * `or` instead of `is not None` silently restores the global default for the
    two values that mean "never abstain" (0.0 and 0)
"""

from app.schemas import ProjectUpdate
from app.services import agentic, generation, query


class TestDepthDetectionIsScriptAware:
    """A Latin-only classifier made the whole agentic path English-only.

    detect_depth gates plan_subqueries (decomposition runs only when depth ==
    "long"), so a question it misreads as "short" never decomposes and never
    gets the structured long-form answer. Because the fallback is a valid
    depth, nothing anywhere reports a problem.
    """

    def test_english_directives_still_work(self):
        assert agentic.detect_depth("Explain the patent filing process") == "long"
        assert agentic.detect_depth("Compare TRIPS and the Nagoya Protocol") == "long"

    def test_a_short_question_is_still_short(self):
        assert agentic.detect_depth("What is a GI tag?") == "short"
        assert agentic.detect_depth("ERR_5521") == "short"

    def test_devanagari_directive_is_long(self):
        # "Explain the patent process" - the exact shape that used to fall
        # through to "short" because \b does not fire on Devanagari.
        assert agentic.detect_depth("पेटेंट प्रक्रिया की व्याख्या कीजिए") == "long"
        assert agentic.detect_depth("आयुर्वेद और आधुनिक चिकित्सा की तुलना करें") == "long"

    def test_chinese_directive_is_long(self):
        assert agentic.detect_depth("请解释青蒿素的发现过程") == "long"

    def test_non_latin_marks_weighting_is_long(self):
        assert agentic.detect_depth("पेटेंट क्या है? 10 अंक") == "long"

    def test_a_short_devanagari_question_stays_short(self):
        # The fix must not make EVERY non-Latin question long - that would
        # double the cost of every simple question in Hindi.
        assert agentic.detect_depth("पेटेंट क्या है?") == "short"


class TestEveryScheduledIndianLanguageReachesTheAgenticPath:
    """Measured coverage, because a list can only cover what someone added.

    The original tuple was English-only and served 7 of 20 languages tested -
    and nothing failed, because "short" is a valid depth. Every row here is a
    directive ("explain the patent process") paired with a plain question, so a
    regression shows up as either lost coverage or a false positive that makes
    cheap questions expensive.
    """

    LONG = [
        ("Hindi", "पेटेंट प्रक्रिया की व्याख्या कीजिए"),
        ("Marathi", "पेटंट प्रक्रियेचे वर्णन करा"),
        ("Bengali", "পেটেন্ট প্রক্রিয়া ব্যাখ্যা করুন"),
        ("Tamil", "காப்புரிமை செயல்முறையை விளக்குக"),
        ("Telugu", "పేటెంట్ ప్రక్రియను వివరించండి"),
        ("Kannada", "ಪೇಟೆಂಟ್ ಪ್ರಕ್ರಿಯೆಯನ್ನು ವಿವರಿಸಿ"),
        ("Malayalam", "പേറ്റന്റ് നടപടിക്രമം വിശദീകരിക്കുക"),
        ("Gujarati", "પેટન્ટ પ્રક્રિયા સમજાવો"),
        ("Punjabi", "ਪੇਟੈਂਟ ਪ੍ਰਕਿਰਿਆ ਦੀ ਵਿਆਖਿਆ ਕਰੋ"),
        ("Odia", "ପେଟେଣ୍ଟ ପ୍ରକ୍ରିୟା ବ୍ୟାଖ୍ୟା କରନ୍ତୁ"),
        ("Urdu", "پیٹنٹ کے عمل کی وضاحت کریں"),
        ("Arabic", "اشرح عملية تسجيل براءات الاختراع"),
        ("Chinese", "请解释专利申请流程"),
        ("Japanese", "特許出願の手続きを説明してください"),
        ("Korean", "특허 출원 절차를 설명하십시오"),
        ("Thai", "อธิบายขั้นตอนการยื่นจดสิทธิบัตร"),
        ("Spanish", "Explique el proceso de patentes"),
        ("French", "Expliquez le processus de brevet"),
        ("German", "Erklären Sie das Patentverfahren"),
    ]

    SHORT = [
        ("Hindi", "पेटेंट क्या है?"),
        ("Tamil", "காப்புரிமை என்றால் என்ன?"),
        ("Kannada", "ಪೇಟೆಂಟ್ ಎಂದರೇನು?"),
        ("Gujarati", "પેટન્ટ શું છે?"),
        ("Urdu", "پیٹنٹ کیا ہے؟"),
        ("Chinese", "什么是专利？"),
        ("Japanese", "特許とは何ですか？"),
        ("Korean", "특허란 무엇입니까?"),
        ("Thai", "สิทธิบัตรคืออะไร"),
        ("Spanish", "¿Qué es una patente?"),
        ("German", "Was ist ein Patent?"),
    ]

    def test_directives_are_recognised(self):
        missed = [n for n, q in self.LONG if agentic.detect_depth(q) != "long"]
        assert not missed, f"agentic path unreachable for: {missed}"

    def test_plain_questions_stay_cheap(self):
        wrong = [n for n, q in self.SHORT if agentic.detect_depth(q) != "short"]
        assert not wrong, f"false positives make these expensive: {wrong}"


class TestLengthFallbackNeedsNoVocabulary:
    """The only rule that covers a language nobody enumerated.

    A word list can never be complete. This catches a substantial question in
    any script - but the threshold has to stay high, because a long answer
    costs several times more tokens than a short one and length is only a proxy
    for wanting one.
    """

    def test_a_very_long_question_is_long_in_any_language(self):
        # Swahili - deliberately a language with no directive entry at all.
        q = (
            "Naomba unieleze kwa kina jinsi mchakato mzima wa kuomba hataza "
            "unavyofanya kazi nchini India kwa dawa za jadi za mimea pamoja na "
            "masharti yote muhimu ya kisheria na nyaraka zinazohitajika sana"
        )
        assert agentic._approx_words(q) >= 25
        assert agentic.detect_depth(q) == "long"

    def test_an_ordinary_question_is_not_dragged_long(self):
        q = "What is the refund window for enterprise customers on annual plans?"
        assert agentic._approx_words(q) < 25
        assert agentic.detect_depth(q) == "short"

    def test_unspaced_scripts_are_counted_by_character(self):
        # Whitespace splitting would call this ONE word, so every CJK question
        # would look trivially short however long it really is. Assert the
        # conversion itself rather than that this particular sentence clears
        # the threshold - the property is what protects the behaviour.
        cjk = "阿育吠陀药物的专利申请流程以及相关法律要求和必要文件的完整说明与分析报告内容"
        assert len(cjk.split()) == 1
        assert agentic._approx_words(cjk) == len(cjk) // 2

    def test_a_long_cjk_question_clears_the_threshold(self):
        cjk = "阿育吠陀药物的专利申请流程以及相关法律要求和必要文件的完整说明与分析报告内容" * 2
        assert agentic.detect_depth(cjk) == "long"

    def test_mixed_script_counts_both_halves(self):
        mixed = "双氢青蒿素 dihydroartemisinin piperaquine 疗效观察"
        assert agentic._approx_words(mixed) > 3


class TestOnlyGroundingReachesThePrompt:
    """Weak chunks must not be citable.

    is_sufficient is a counting test, not a filter: one source at 0.21 could
    authorise the answer while sources at 0.05 sat in the prompt as [2] and [3]
    and came back to the caller in `sources`.
    """

    def _srcs(self, *sims):
        return [
            {"filename": "f.pdf", "page_number": None, "chunk_index": i,
             "content": "c", "similarity": s}
            for i, s in enumerate(sims)
        ]

    def test_below_floor_is_dropped(self):
        kept = agentic.grounding_only(self._srcs(0.81, 0.42, 0.05), 0.4)
        assert [s["similarity"] for s in kept] == [0.81, 0.42]

    def test_the_floor_itself_is_kept(self):
        kept = agentic.grounding_only(self._srcs(0.4, 0.39), 0.4)
        assert [s["similarity"] for s in kept] == [0.4]

    def test_never_returns_empty(self):
        # min_strong=0 means "never abstain": sufficiency passes with nothing
        # over the floor, and filtering to nothing would leave the model no
        # context at all. Falling back to the unfiltered list is the safe end.
        kept = agentic.grounding_only(self._srcs(0.1, 0.05), 0.9)
        assert len(kept) == 2

    def test_gather_context_filters_what_it_returns(self):
        ctx = agentic.gather_context(
            question="what is it",
            retrieve_fn=lambda q, k: self._srcs(0.9, 0.02),
            plan_fn=lambda q: [q],
            clarify_fn=lambda q: ["?"],
            top_k=5,
            min_similarity=0.5,
            min_strong=1,
            max_rounds=2,
        )
        assert ctx.needs_clarification is False
        assert [s["similarity"] for s in ctx.sources] == [0.9]


class TestPolicyIsInTheCacheSignature:
    """A toggle absent from the cache key reads as "the feature is broken".

    Both answer caches compare one signature for equality. Changing the
    grounding floor or the disclaimer changes the ANSWER but not the CONTENT,
    so without this the pre-change answer keeps being served for up to 24h.
    """

    class _P:
        content_version = 7
        min_similarity = 0.2
        min_strong = 1
        answer_language = None
        answer_disclaimer = None

    def test_same_policy_same_signature(self):
        assert query._answer_signature(self._P()) == query._answer_signature(self._P())

    def test_raising_the_floor_changes_it(self):
        p = self._P()
        before = query._answer_signature(p)
        p.min_similarity = 0.45
        assert query._answer_signature(p) != before

    def test_setting_a_language_changes_it(self):
        p = self._P()
        before = query._answer_signature(p)
        p.answer_language = "Hindi"
        assert query._answer_signature(p) != before

    def test_setting_a_disclaimer_changes_it(self):
        p = self._P()
        before = query._answer_signature(p)
        p.answer_disclaimer = "Information only, not legal advice."
        assert query._answer_signature(p) != before

    def test_content_version_still_dominates(self):
        p = self._P()
        before = query._answer_signature(p)
        p.content_version = 8
        assert query._answer_signature(p) != before


class TestZeroIsNotFalsy:
    """0.0 and 0 mean "never abstain" - `or` would discard them."""

    class _P:
        min_similarity = 0.0
        min_strong = 0

    def test_zero_survives_the_read(self):
        assert query._grounding_policy(self._P()) == (0.0, 0)

    def test_a_pre_0032_row_falls_back_to_the_globals(self):
        from app.config import settings

        class Old:
            pass

        assert query._grounding_policy(Old()) == (
            settings.agentic_min_similarity,
            settings.agentic_min_strong,
        )


class TestCitedSourcesAreMarked:
    """`sources` is everything retrieved, not what the answer used."""

    def _srcs(self, n):
        return [
            {"filename": f"{i}.pdf", "page_number": None, "chunk_index": i,
             "content": "c", "similarity": 0.5}
            for i in range(n)
        ]

    def test_markers_map_to_zero_based_positions(self):
        out = query._mark_cited("As shown in [1] and [3].", self._srcs(4))
        assert [s["cited"] for s in out] == [True, False, True, False]

    def test_an_answer_citing_nothing_marks_nothing(self):
        out = query._mark_cited("No citation here.", self._srcs(3))
        assert not any(s["cited"] for s in out)

    def test_out_of_range_markers_are_ignored(self):
        # The markers come from model output, so [9] with 2 sources is possible
        # and must not raise.
        out = query._mark_cited("See [9].", self._srcs(2))
        assert [s["cited"] for s in out] == [False, False]

    def test_a_clarification_has_no_sources(self):
        assert query._mark_cited(None, []) == []


class TestPromptCarriesThePolicy:
    def test_default_mirrors_the_question_language(self):
        p = generation.system_prompt_for("short")
        assert "same language the question was asked in" in p

    def test_a_forced_language_is_named(self):
        p = generation.system_prompt_for("short", "Hindi", None)
        assert "entire answer in Hindi" in p
        assert "same language the question was asked in" not in p

    def test_the_disclaimer_is_reproduced_verbatim(self):
        notice = "Information only - not a substitute for legal advice."
        p = generation.system_prompt_for("long", None, notice)
        assert notice in p
        assert "never reworded" in p

    def test_depth_still_selects_the_base_prompt(self):
        assert generation.LONG_SYSTEM_PROMPT in generation.system_prompt_for("long")
        assert generation.SHORT_SYSTEM_PROMPT in generation.system_prompt_for("short")

    def test_policy_for_tolerates_a_pre_0032_project(self):
        class Old:
            pass

        assert generation.policy_for(Old()) == (None, None)


class TestUpdateValidation:
    """The API bounds must match the CHECK constraints in 0032."""

    def test_similarity_is_bounded_to_cosine_range(self):
        import pytest
        from pydantic import ValidationError

        ProjectUpdate(min_similarity=0.0)
        ProjectUpdate(min_similarity=1.0)
        with pytest.raises(ValidationError):
            ProjectUpdate(min_similarity=1.5)
        with pytest.raises(ValidationError):
            ProjectUpdate(min_similarity=-0.1)

    def test_min_strong_is_bounded(self):
        import pytest
        from pydantic import ValidationError

        ProjectUpdate(min_strong=0)
        with pytest.raises(ValidationError):
            ProjectUpdate(min_strong=-1)
