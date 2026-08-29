"""Agentic retrieval loop over a project's brain.

Flat RAG embeds the whole question once and answers from the top-k chunks. That
works for a focused question ("what is deep learning") but fails a broad,
multi-part, exam-style question ("explain deep learning, its types and
applications - 13 marks"): one embedding matches poorly, the retrieved chunks
miss whole sub-topics, and the model hits its "I don't know" guardrail.

This module adds a loop:

  1. detect_depth   - does this question want a short answer or a long one?
  2. plan_subqueries - break a long question into focused retrieval queries
  3. retrieve each, merge_sources - gather a broad, de-duplicated context
  4. is_sufficient   - did we actually ground enough to answer?
  5. if yes  -> answer (depth-aware: long questions get a structured answer)
     if no   -> escalate to a human clarification step instead of refusing
"""
import re
from collections.abc import Callable
from dataclasses import dataclass, field

# Directive verbs that signal a question wants a thorough, structured answer.
#
# Latin-script languages share this tuple because they share \b word
# boundaries; other scripts are matched by substring below, where \b does not
# apply.
_LONG_DIRECTIVES = (
    # English
    "explain", "discuss", "describe", "elaborate", "compare", "contrast",
    "analyze", "analyse", "evaluate", "illustrate", "examine", "outline",
    "derive", "summarize", "summarise", "justify", "differentiate", "list",
    # Spanish
    "explique", "explica", "describa", "compare", "analice", "discuta",
    "evalúe", "resuma", "enumere",
    # French
    "expliquez", "explique", "décrivez", "comparez", "analysez", "discutez",
    "évaluez", "résumez", "énumérez",
    # German
    "erklären", "erkläre", "erläutern", "beschreiben", "vergleichen",
    "analysieren", "diskutieren", "bewerten", "zusammenfassen",
    # Portuguese / Italian - the remaining widely-used Latin-script pair
    "explique", "descreva", "compare", "analise", "discuta",
    "spiega", "descrivi", "confronta", "analizza", "discuti",
)
# The same directives in other scripts.
#
# WHY THIS EXISTS: the tuple above is ASCII-only, and \b in Python's `re` is
# defined on word characters, so a Devanagari question matched NEITHER regex
# and always fell through to "short". That silently skipped plan_subqueries
# (decomposition is gated on depth == "long"), which meant the entire agentic
# multi-query path - and the structured long-form answer - were unreachable in
# any non-Latin language. No amount of non-English content fixes that; it is
# the classifier, not the corpus.
#
# Substring matching, not \b: Devanagari and CJK are not word-delimited the way
# \b assumes, so a boundary assertion would fail on exactly the scripts this
# is here to serve.
_LONG_DIRECTIVES_INTL = (
    # Hindi / Marathi (Devanagari)
    "व्याख्या", "समझाइए", "समझाएं", "वर्णन", "विवेचना", "तुलना", "अंतर",
    "मूल्यांकन", "विश्लेषण", "चर्चा", "सूची", "प्रकिये",
    # Bengali / Assamese
    "ব্যাখ্যা", "বর্ণনা", "তুলনা", "আলোচনা", "বিশ্লেষণ",
    # Tamil
    "விளக்கு", "விவரி", "ஒப்பிடு", "ஆராய்", "பட்டியலிடு",
    # Telugu
    "వివరించండి", "వర్ణించండి", "పోల్చండి", "చర్చించండి", "విశ్లేషించండి",
    # Kannada
    "ವಿವರಿಸಿ", "ವರ್ಣಿಸಿ", "ಹೋಲಿಸಿ", "ಚರ್ಚಿಸಿ", "ವಿಶ್ಲೇಷಿಸಿ",
    # Malayalam
    "വിശദീകരി", "വിവരി", "താരതമ്യ", "ചർച്ച", "വിശകലനം",
    # Gujarati
    "સમજાવો", "વર્ણવો", "સરખામણી", "ચર્ચા", "વિશ્લેષણ",
    # Punjabi (Gurmukhi)
    "ਵਿਆਖਿਆ", "ਸਮਝਾਓ", "ਵਰਣਨ", "ਤੁਲਨਾ", "ਚਰਚਾ", "ਵਿਸ਼ਲੇਸ਼ਣ",
    # Odia
    "ବ୍ୟାଖ୍ୟା", "ବର୍ଣ୍ଣନା", "ତୁଳନା", "ଆଲୋଚନା", "ବିଶ୍ଳେଷଣ",
    # Urdu / Arabic (Arabic script)
    "وضاحت", "بیان", "موازنہ", "تجزیہ", "تشریح",
    "اشرح", "وضح", "قارن", "ناقش", "حلل", "لخص",
    # Chinese - the supplied corpus is bilingual, so this is not hypothetical
    "解释", "说明", "描述", "比较", "分析", "讨论", "评价", "概述",
    # Japanese
    "説明", "述べ", "比較", "論じ", "分析", "要約",
    # Korean
    "설명", "서술", "비교", "논하", "분석", "요약",
    # Thai
    "อธิบาย", "เปรียบเทียบ", "วิเคราะห์", "อภิปราย", "สรุป", "บรรยาย",
)

# Scripts that are not whitespace-delimited, so "word count" has to be
# approximated from character count instead.
_UNSPACED_RANGES = (
    (0x3040, 0x30FF),  # Japanese kana
    (0x3400, 0x4DBF),  # CJK extension A
    (0x4E00, 0x9FFF),  # CJK unified ideographs
    (0x0E00, 0x0E7F),  # Thai
)
# "13 marks", "13 mark", "13marks" - an exam weighting demands a full answer.
_MARKS_RE = re.compile(r"\b\d{1,2}\s*marks?\b", re.IGNORECASE)
# अंक / मार्क्स - the same weighting written in Devanagari.
_MARKS_INTL_RE = re.compile(r"\d{1,2}\s*(?:अंक|मार्क्स|மதிப்பெண்|分)")
_DIRECTIVE_RE = re.compile(
    r"\b(" + "|".join(_LONG_DIRECTIVES) + r")\b", re.IGNORECASE
)


# Approximate words past which a question is treated as wanting a long answer,
# whatever language it is in.
_LONG_WORD_COUNT = 25
# Chinese/Japanese/Thai average roughly this many characters per word, so a
# character count divided by it approximates the word count those scripts do
# not expose through whitespace.
_CHARS_PER_UNSPACED_WORD = 2


def _approx_words(question: str) -> int:
    """Word count that works for scripts without spaces.

    Whitespace splitting counts a whole Chinese sentence as one word, which
    would make every CJK question look trivially short. Characters in the
    unspaced ranges are counted separately and converted at
    _CHARS_PER_UNSPACED_WORD; everything else is counted by whitespace.
    """
    unspaced_chars = []
    rest = []
    for ch in question:
        code = ord(ch)
        if any(lo <= code <= hi for lo, hi in _UNSPACED_RANGES):
            unspaced_chars.append(ch)
        else:
            rest.append(ch)
    # The unspaced characters are REMOVED before the whitespace count, not
    # merely counted alongside it. Leaving them in double-counts: a pure CJK
    # sentence is one whitespace "word" AND len/2 character-derived words, so
    # it came out one higher than it should. Mixed text (a Chinese abstract
    # carrying English drug names) still contributes both halves, which is the
    # behaviour that matters.
    spaced = len("".join(rest).split())
    return spaced + len(unspaced_chars) // _CHARS_PER_UNSPACED_WORD


def detect_depth(question: str) -> str:
    """Classify how much answer a question wants: "short" or "long".

    Heuristic and deterministic (no model call): an explicit marks weighting or
    a broad directive verb means the caller wants a comprehensive answer.

    Script-aware - see _LONG_DIRECTIVES_INTL for why a Latin-only classifier
    disabled the whole agentic path for other languages.
    """
    if _MARKS_RE.search(question) or _MARKS_INTL_RE.search(question):
        return "long"
    if _DIRECTIVE_RE.search(question):
        return "long"
    if any(d in question for d in _LONG_DIRECTIVES_INTL):
        return "long"
    # Last resort, and the only rule that needs no vocabulary at all.
    #
    # The two rules above are lists of words, and a list can only ever cover
    # the languages someone remembered to add - measured, the original
    # English-only tuple served 7 of 20 languages. This catches a substantial
    # question in a language nobody has enumerated, including one that does not
    # exist yet.
    #
    # The threshold is deliberately high. A directive verb is EVIDENCE that a
    # long answer is wanted; length is only a proxy, so it must not fire on the
    # ordinary questions the short path handles well and cheaply - a long
    # answer costs several times more tokens. 25 approximate words is well past
    # anything conversational.
    if _approx_words(question) >= _LONG_WORD_COUNT:
        return "long"
    return "short"


# Leading list markers a model tends to emit: "1.", "2)", "-", "*", "•".
_BULLET_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")


def parse_subqueries(raw: str, max_n: int) -> list[str]:
    """Turn a model's line-per-query output into clean sub-query strings.

    Strips numbering/bullets and blank lines, de-duplicates case-insensitively
    while preserving order, and caps the result to ``max_n``.
    """
    out: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        cleaned = _BULLET_RE.sub("", line).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= max_n:
            break
    return out


PLAN_SYSTEM_PROMPT = (
    "You are a retrieval planner. Break the user's question into a short list of "
    "focused sub-questions that, answered together, fully cover it. Output one "
    "sub-question per line - no numbering, no commentary, no preamble."
)


def plan_subqueries(llm, question: str, max_n: int = 5) -> list[str]:
    """Decompose a broad question into focused retrieval queries.

    Asks ``llm`` for sub-questions, then prepends the literal question (so the
    loop always retrieves it too), de-duplicates and caps to ``max_n``. Falls
    back to just the original question if the model returns nothing usable.
    """
    raw = llm.generate(PLAN_SYSTEM_PROMPT, question)
    parts = parse_subqueries(raw, max_n)
    merged = parse_subqueries("\n".join([question, *parts]), max_n)
    return merged or [question]


CLARIFY_SYSTEM_PROMPT = (
    "You help a retrieval system that could not find enough information to answer "
    "the user's question confidently. Ask 1-3 short clarifying questions that would "
    "narrow it down - for example which topic, document, chapter, or scope is "
    "meant. Output one question per line - no numbering, no commentary."
)

_GENERIC_CLARIFICATION = (
    "Could you add a little more detail? For example, name the specific topic, "
    "chapter, or document you have in mind."
)


def request_clarification(llm, question: str, max_n: int = 3) -> list[str]:
    """Ask the model for clarifying questions when grounding came up short.

    Falls back to a single generic prompt if the model returns nothing usable, so
    the caller always has something to put in front of the human.
    """
    raw = llm.generate(CLARIFY_SYSTEM_PROMPT, question)
    questions = parse_subqueries(raw, max_n)
    return questions or [_GENERIC_CLARIFICATION]


CONDENSE_SYSTEM_PROMPT = (
    "Given a conversation and a follow-up message, rewrite the follow-up as a "
    "standalone question that can be understood on its own. Resolve references "
    "like 'it', 'that', 'this', 'the previous one'. If the follow-up is already "
    "standalone, return it unchanged. Output only the rewritten question - no "
    "preamble, no quotes."
)


def _format_history(history: list[dict], max_turns: int) -> str:
    """Render the most recent turns as a compact transcript for the model."""
    lines: list[str] = []
    for turn in history[-max_turns:]:
        lines.append(f"User: {turn['question']}")
        lines.append(f"Assistant: {turn['answer']}")
    return "\n".join(lines)


def condense_question(
    llm, history: list[dict], question: str, max_turns: int = 6
) -> str:
    """Rewrite a follow-up into a standalone question using conversation history.

    This is what gives the loop a memory: "give a brief summary" after a turn
    about deep learning becomes "Give a brief summary of deep learning", so
    retrieval and answering work on a self-contained query. With no history the
    question is returned unchanged and the model is never called (no cost).
    """
    if not history:
        return question
    convo = _format_history(history, max_turns)
    user_prompt = (
        f"Conversation so far:\n{convo}\n\n"
        f"Follow-up: {question}\n\nStandalone question:"
    )
    rewritten = llm.generate(CONDENSE_SYSTEM_PROMPT, user_prompt).strip()
    return rewritten or question


def clarification_message(questions: list[str]) -> str:
    """Render clarifying questions as a friendly, human-facing message."""
    intro = (
        "I couldn't find enough in this project to answer that confidently. "
        "To help me narrow it down:"
    )
    bullets = "\n".join(f"- {q}" for q in questions)
    return f"{intro}\n{bullets}"


def merge_sources(lists: list[list[dict]]) -> list[dict]:
    """Combine retrieved chunks from several sub-queries into one ranked list.

    The same chunk surfaced by multiple sub-queries is kept once with its best
    similarity; distinct chunks (and distinct memories) are all preserved. The
    result is sorted by similarity, highest first. Content is part of the dedup
    key so two different memories that share a synthetic index stay distinct.
    """
    best: dict[tuple, dict] = {}
    for source in (s for lst in lists for s in lst):
        key = (
            source["filename"],
            source.get("page_number"),
            source["chunk_index"],
            source["content"],
        )
        current = best.get(key)
        if current is None or source["similarity"] > current["similarity"]:
            best[key] = source
    return sorted(best.values(), key=lambda s: s["similarity"], reverse=True)


# How far the grounding floor may be relaxed on the LAST attempt, as a fraction
# of the configured threshold. 0.85 mirrors RAGFlow's 0.2 -> 0.17 fallback.
#
# Small on purpose. A large relaxation would answer from material the system
# does not really believe in, which is the failure the threshold exists to
# prevent; a small one recovers the near-misses that were never worth
# interrupting a human over.
RELAXED_SIMILARITY_RATIO = 0.85


def is_sufficient(
    sources: list[dict], min_similarity: float, min_strong: int
) -> bool:
    """Did the loop ground enough to answer, or must it ask the human?

    "Enough" means at least ``min_strong`` sources clear ``min_similarity``.
    Below that the context is too thin to answer faithfully, so the caller
    escalates to a clarification step rather than guessing.
    """
    strong = sum(1 for s in sources if s["similarity"] >= min_similarity)
    return strong >= min_strong


def grounding_only(sources: list[dict], floor: float) -> list[dict]:
    """Drop what did not clear the floor that authorised the answer.

    is_sufficient COUNTS how many sources clear the bar; it never filtered the
    list it was handed. So the whole retrieved set - including chunks scoring
    near zero - reached the prompt as numbered, citable blocks and was reported
    to the caller as `sources`. One chunk at 0.21 could authorise an answer
    while chunks at 0.05 sat in the context as [2] and [3], available to be
    cited as if they supported the claim.

    Called only on the paths where sufficiency already passed, so the result is
    non-empty by construction. The fallback is belt-and-braces for min_strong=0
    ("never abstain"), where sufficiency passes without anything clearing the
    floor and filtering would leave the model nothing at all.
    """
    kept = [s for s in sources if s["similarity"] >= floor]
    return kept or sources


@dataclass
class AgenticResult:
    """Outcome of the loop: either a grounded answer, or a request for help."""

    answer: str | None
    sources: list[dict]
    depth: str
    sub_queries: list[str]
    rounds: int
    needs_clarification: bool
    clarification_questions: list[str] = field(default_factory=list)
    # Token usage of the LLM calls that PRODUCED this result (plan + generate,
    # or plan + clarify) - not the condense step, which runs before the caches
    # and is spent again on every follow-up. Serialized into BOTH answer caches
    # with the rest of the dataclass, so a later cache hit can report exactly
    # how many tokens it saved instead of estimating. None means "was not
    # measured" (e.g. a streamed generation, where providers report nothing) -
    # never 0, which would claim a real measurement of zero. Defaults keep
    # pre-existing cache payloads (which lack these keys) deserializable.
    gen_prompt_tokens: int | None = None
    gen_completion_tokens: int | None = None
    # WHICH model produced the counts above. Without it a cache hit knows how
    # many tokens it saved but not what they were worth, and the saving could
    # only be estimated from a blended account-wide rate. With it the hit
    # prices its own saving exactly, through the same table as a live call.
    # Deliberately the model of the ORIGINAL run: if the project later switches
    # models, what was avoided is still what was once actually spent.
    gen_model: str | None = None


@dataclass
class GatheredContext:
    """The loop's retrieval outcome BEFORE the final answer is written.

    Splitting "gather" from "generate" lets a streaming caller do the (blocking)
    retrieval/planning first, then stream just the answer token by token.
    """

    sources: list[dict]
    depth: str
    sub_queries: list[str]
    rounds: int
    needs_clarification: bool
    clarification_questions: list[str] = field(default_factory=list)


def gather_context(
    *,
    question: str,
    retrieve_fn: Callable[[str, int], list[dict]],
    plan_fn: Callable[[str], list[str]],
    clarify_fn: Callable[[str], list[str]],
    top_k: int = 5,
    min_similarity: float = 0.3,
    min_strong: int = 2,
    max_rounds: int = 2,
) -> GatheredContext:
    """Run the retrieval loop and return the gathered context (no generation).

    Detects depth, decomposes a broad question, retrieves and merges over up to
    ``max_rounds``, and either returns enough grounding to answer, or the
    clarifying questions to hand back to the human.
    """
    depth = detect_depth(question)
    sub_queries = plan_fn(question) if depth == "long" else [question]

    gathered: list[dict] = []
    queries = list(sub_queries)
    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        round_results = [retrieve_fn(q, top_k) for q in queries]
        gathered = merge_sources([gathered, *round_results])
        if is_sufficient(gathered, min_similarity, min_strong):
            return GatheredContext(
                sources=grounding_only(gathered, min_similarity),
                depth=depth,
                sub_queries=sub_queries,
                rounds=rounds,
                needs_clarification=False,
            )
        # Not enough yet - broaden the net and re-query the literal question.
        queries = [question]
        top_k = min(top_k * 2, 20)

    # Before giving up, try once at a RELAXED floor.
    #
    # Borrowed from RAGFlow, which drops its similarity threshold from 0.2 to
    # 0.17 (and min_match from 0.3 to 0.1) when a pass comes back empty rather
    # than escalating immediately.
    #
    # The case it fixes here: the best source scored 0.19 against a floor of
    # 0.2, so the loop asked a clarifying question about material it had
    # already found. Widening top_k - the only thing the loop did before - does
    # not help that at all, because the problem was never the number of
    # candidates, it was the bar.
    #
    # Deliberately NOT the same as lowering min_similarity outright: this only
    # applies after every normal round has failed, and it still needs
    # min_strong sources to clear the relaxed floor, so a question the corpus
    # genuinely does not cover still reaches a human.
    relaxed = min_similarity * RELAXED_SIMILARITY_RATIO
    if relaxed < min_similarity and is_sufficient(gathered, relaxed, min_strong):
        return GatheredContext(
            # Filtered at the RELAXED floor - the bar that actually authorised
            # this answer - not at min_similarity, which nothing here cleared.
            sources=grounding_only(gathered, relaxed),
            depth=depth,
            sub_queries=sub_queries,
            rounds=rounds,
            needs_clarification=False,
        )

    # Loop exhausted without enough grounding → keep a human in the loop.
    return GatheredContext(
        sources=gathered,
        depth=depth,
        sub_queries=sub_queries,
        rounds=rounds,
        needs_clarification=True,
        clarification_questions=clarify_fn(question),
    )


def run_agentic_query(
    *,
    question: str,
    retrieve_fn: Callable[[str, int], list[dict]],
    plan_fn: Callable[[str], list[str]],
    generate_fn: Callable[[str, list[dict], str], str],
    clarify_fn: Callable[[str], list[str]],
    top_k: int = 5,
    min_similarity: float = 0.3,
    min_strong: int = 2,
    max_rounds: int = 2,
) -> AgenticResult:
    """Run the agentic retrieval loop, escalating to a human when it gets stuck.

    Dependency-injected so it carries no DB or provider knowledge: ``retrieve_fn``
    runs one vector search, ``plan_fn`` decomposes a broad question, ``generate_fn``
    writes the (depth-aware) answer, and ``clarify_fn`` produces clarifying
    questions. Gathers context, then either answers or asks for clarification.
    """
    ctx = gather_context(
        question=question,
        retrieve_fn=retrieve_fn,
        plan_fn=plan_fn,
        clarify_fn=clarify_fn,
        top_k=top_k,
        min_similarity=min_similarity,
        min_strong=min_strong,
        max_rounds=max_rounds,
    )
    if ctx.needs_clarification:
        return AgenticResult(
            answer=None,
            sources=ctx.sources,
            depth=ctx.depth,
            sub_queries=ctx.sub_queries,
            rounds=ctx.rounds,
            needs_clarification=True,
            clarification_questions=ctx.clarification_questions,
        )
    return AgenticResult(
        answer=generate_fn(question, ctx.sources, ctx.depth),
        sources=ctx.sources,
        depth=ctx.depth,
        sub_queries=ctx.sub_queries,
        rounds=ctx.rounds,
        needs_clarification=False,
    )
