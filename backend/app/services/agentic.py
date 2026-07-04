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
_LONG_DIRECTIVES = (
    "explain", "discuss", "describe", "elaborate", "compare", "contrast",
    "analyze", "analyse", "evaluate", "illustrate", "examine", "outline",
    "derive", "summarize", "summarise", "justify", "differentiate", "list",
)
# "13 marks", "13 mark", "13marks" - an exam weighting demands a full answer.
_MARKS_RE = re.compile(r"\b\d{1,2}\s*marks?\b", re.IGNORECASE)
_DIRECTIVE_RE = re.compile(
    r"\b(" + "|".join(_LONG_DIRECTIVES) + r")\b", re.IGNORECASE
)


def detect_depth(question: str) -> str:
    """Classify how much answer a question wants: "short" or "long".

    Heuristic and deterministic (no model call): an explicit marks weighting or
    a broad directive verb means the caller wants a comprehensive answer.
    """
    if _MARKS_RE.search(question):
        return "long"
    if _DIRECTIVE_RE.search(question):
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
    questions. The loop:

      * detects depth - a broad question is decomposed into sub-queries, a
        focused one is searched as-is;
      * retrieves every query and merges the results into a widening context;
      * answers as soon as the context is sufficient (depth threaded through);
      * otherwise broadens and retries up to ``max_rounds``, and only then hands
        back to the human with clarifying questions instead of guessing.
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
            return AgenticResult(
                answer=generate_fn(question, gathered, depth),
                sources=gathered,
                depth=depth,
                sub_queries=sub_queries,
                rounds=rounds,
                needs_clarification=False,
            )
        # Not enough yet - broaden the net and re-query the literal question.
        queries = [question]
        top_k = min(top_k * 2, 20)

    # Loop exhausted without enough grounding → keep a human in the loop.
    return AgenticResult(
        answer=None,
        sources=gathered,
        depth=depth,
        sub_queries=sub_queries,
        rounds=rounds,
        needs_clarification=True,
        clarification_questions=clarify_fn(question),
    )
