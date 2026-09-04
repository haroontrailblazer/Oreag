import logging

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Project
from ..providers import resolver
from ..providers.registry import get_llm
from . import cross_lingual
from .tracing import observed_generate, observed_stream

logger = logging.getLogger(__name__)

# A focused question wants a short, factual answer. Answer DIRECTLY from the
# sources - no hedging preamble ("the provided context does not explicitly...")
# and no meta-commentary about the context; the reader wants the answer, not a
# report on what the documents contain.
SHORT_SYSTEM_PROMPT = (
    "You are a knowledgeable assistant answering from the provided source "
    "material. Answer the question directly and confidently in your own voice, "
    "as if the knowledge is yours. Do NOT start with disclaimers like 'the "
    "provided context does not explicitly define' or 'based on the context', and "
    "do NOT mention 'the context', 'the sources', or 'the documents' in your "
    "answer - just give the answer. Cite the blocks you used inline as [1], [2], "
    "etc. Keep it concise and factual. Only if the sources genuinely contain "
    "nothing relevant, say briefly that the documents don't cover it - never "
    "invent facts."
)

# A broad, multi-part (exam-style) question wants a long, structured answer. The
# agentic loop has already gathered a wide context, so the model should write the
# full answer it can support - directly and confidently, NOT bailing with "I
# don't know" or hedging about the context when it is only partial.
LONG_SYSTEM_PROMPT = (
    "You are an expert assistant answering an exam-style question that calls for a "
    "thorough, well-structured answer. Answer directly and confidently in your own "
    "voice - do NOT preface with disclaimers like 'the provided context does not "
    "explicitly...' or 'based on the context', and do NOT mention 'the context', "
    "'the sources' or 'the documents'; just teach the topic. Use ALL of the "
    "relevant source material and write a comprehensive answer: open with a short "
    "overview, then cover each part under clear Markdown headings or numbered "
    "points, and finish with a brief summary where it helps. Cite the blocks you "
    "used inline as [1], [2], etc. If "
    "the material covers the topic only partially, answer as fully as it allows "
    "and state plainly which parts are not covered - do NOT refuse outright, and "
    "never invent facts."
)

# Back-compat alias for any caller importing the old name.
SYSTEM_PROMPT = SHORT_SYSTEM_PROMPT


def system_prompt_for(
    depth: str,
    language: str | None = None,
    disclaimer: str | None = None,
) -> str:
    """Pick the grounding prompt for the detected answer depth.

    ``language`` and ``disclaimer`` come from the project (migration 0032) and
    are appended rather than folded into the constants, so a project that sets
    neither gets byte-identical output to before - which is what keeps both
    answer caches valid for existing projects.

    Language is APPENDED, not substituted: the base prompts say nothing about
    language, so without this a question asked in Hindi could be answered in
    English purely because the sources were English. Mirroring is the default
    because it needs no configuration; ``language`` forces one instead.
    """
    base = LONG_SYSTEM_PROMPT if depth == "long" else SHORT_SYSTEM_PROMPT
    extra = []
    if language:
        extra.append(
            f"Write the entire answer in {language}, regardless of the language "
            "of the question or of the source material."
        )
    else:
        extra.append(
            "Write the answer in the same language the question was asked in, "
            "even when the source material is in another language."
        )
    if disclaimer:
        # Verbatim and last, so a regulator-facing notice cannot be paraphrased
        # into something weaker by the model.
        extra.append(
            "End every answer with this notice on its own line, reproduced "
            f"exactly and never reworded: {disclaimer}"
        )
    return base + " " + " ".join(extra)


def policy_for(project) -> tuple[str | None, str | None]:
    """The project's (language, disclaimer), tolerant of older rows.

    getattr rather than attribute access: tests and any caller holding a
    lightweight stand-in for Project should not have to know about 0032.
    """
    return (
        getattr(project, "answer_language", None),
        getattr(project, "answer_disclaimer", None),
    )


def build_user_prompt(question: str, sources: list[dict]) -> str:
    def _label(s: dict) -> str:
        page = s.get("page_number")
        return s["filename"] + (f" (page {page})" if page is not None else "")

    context = "\n\n".join(
        f"[{i + 1}] {_label(s)}:\n{s['content']}" for i, s in enumerate(sources)
    )
    return f"Context:\n{context}\n\nQuestion: {question}"


def _loaded_state(db: Session) -> list[tuple[object, dict]]:
    """Snapshot the loaded attribute values of every clean persistent object.

    Best effort by design: a caller passing a session stand-in with no identity
    map snapshots nothing. Objects with unflushed changes are skipped on
    purpose - a rollback SHOULD revert those.
    """
    try:
        objects = list(db.identity_map.values())
    except Exception:
        return []
    snapshot: list[tuple[object, dict]] = []
    for obj in objects:
        try:
            state = sa_inspect(obj)
            if state.modified:
                continue
            snapshot.append((state, dict(state.dict)))
        except Exception:
            continue
    return snapshot


def _restore_loaded_state(snapshot: list[tuple[object, dict]]) -> None:
    """Put snapshotted values back and mark them loaded-and-clean again.

    Writing straight into ``state.dict`` restores the values without firing
    attribute events, so nothing becomes dirty; ``_commit_all`` then clears the
    expired flag so ``inspect(obj).unloaded`` is empty again. That last call is
    SQLAlchemy-internal and therefore guarded: if a future release drops it the
    values are still back in place and still short-circuit the refresh, which
    is the property that matters.
    """
    for state, values in snapshot:
        try:
            for key, value in values.items():
                if key not in state.dict:
                    state.dict[key] = value
            state._commit_all(state.dict)
        except Exception:
            continue


def enforce_language(user_prompt: str, language: str | None) -> str:
    """Repeat a PINNED answer language at the very end of the user prompt.

    MEASURED, and the reason this is not merely belt-and-braces. The system
    prompt already says "write the entire answer in English, regardless of the
    language of the question or of the source material" - wording that cannot
    be made any more explicit - and gpt-4o-mini still answered a Hindi
    question in Hindi three times out of three. The question's own language
    beat the instruction.

    The variable left was POSITION: the system prompt sits far from the point
    of generation and the user prompt ends right next to it. Repeating one
    short sentence there took a pinned language from 3/9 to 9/9 across Hindi,
    Tamil and English questions.

    Applied ONLY when a project has pinned a language AND asked for it always.
    Every other request gets `build_user_prompt` byte-for-byte as before, so
    nothing already cached is disturbed.
    """
    if not language:
        return user_prompt
    return user_prompt + "\n\nWrite the entire answer in " + language + "."


def release_connection(db: Session | None) -> None:
    """Hand this session's pooled DB connection back before a provider call.

    A completion blocks for seconds (a streamed one, sometimes minutes) and
    needs no database at all. Holding the pooled connection across that wait is
    what drains the pool under load: the connection is idle, but no other
    request can have it.

    Measured against a pool-instrumented engine on the pinned SQLAlchemy
    (2.0.50): ``Session.commit()`` ends the transaction and checks the DBAPI
    connection back in - ``pool.checkedout()`` drops to 0 - and the session
    transparently checks a fresh one out on its next statement, so callers keep
    using ``db`` afterwards exactly as before. ``SessionLocal`` sets
    ``expire_on_commit=False``, so loaded ORM objects (the Project) keep their
    values across the release: no staleness, and no refresh SELECT on the way
    back. ``close()`` would release too, but it also detaches every loaded
    object, so ``commit()`` is the smaller hammer.

    ``expire_on_commit=False`` buys nothing on the FAILURE branch, though:
    ``Session.rollback()`` expires every persistent instance regardless of it -
    right after one, ``inspect(obj).unloaded`` lists every mapped column
    (pinned in tests/test_query.py::TestReleaseSemantics). Left alone, the
    caller's Project
    would silently re-SELECT on its next attribute read: a hidden connection
    checkout in code that believes it touches no database, and values that may
    have changed mid-request - a model PATCHed while the answer was generating
    would be stamped onto the semantic-cache row of an answer the OLD model
    wrote. So the loaded values are snapshotted before the rollback and put
    back after it, and the invariant "a release never changes what a loaded
    object says" holds on both branches.

    Nothing is pending at the call sites - retrieval is read-only and the
    query-log / semantic-cache writes come later - so this commits no work of
    its own; it only ends the read transaction. Best effort: failing to give
    the connection back must never fail the answer.
    """
    if db is None:  # standalone callers may generate without a session
        return
    if not settings.db_release_during_provider_io:
        # The kill switch. Guarding here rather than at each call site means
        # every release point is covered by the one flag, and it cannot drift
        # as call sites are added. The release itself has since been exercised
        # against live Supabase (checkedout 1 -> 0 across a provider call, the
        # loaded Project still readable afterwards), but the switch stays:
        # DB_RELEASE_DURING_PROVIDER_IO=false restores the old
        # hold-for-the-whole-request behaviour with an env change and a
        # restart, no redeploy.
        return
    try:
        db.commit()
    except Exception:
        logger.warning(
            "Could not release the DB connection before provider I/O",
            exc_info=True,
        )
        snapshot = _loaded_state(db)
        try:
            db.rollback()  # rollback ends the transaction (and releases) too
        except Exception:
            pass
        _restore_loaded_state(snapshot)


def generate_answer(
    db: Session,
    project: Project,
    question: str,
    sources: list[dict],
    depth: str = "short",
    llm_fn=None,
    usage_acc=None,
) -> str:
    # ``usage_acc`` (any object with .add(TokenUsage)) receives what this call
    # consumed - query.py passes its per-request accumulator so the final
    # generation counts toward the same billing figure as condense/plan.
    # query.py passes its per-request LLM getter (key resolved at most once)
    # as ``llm_fn``; standalone callers omit it and resolution happens here.
    if llm_fn is not None:
        llm = llm_fn()
    else:
        api_key = resolver.resolve_llm_key(db, project)
        llm = get_llm(project.llm_provider, project.llm_model, api_key)
    language, disclaimer = policy_for(project)
    pinned_always = bool(language) and getattr(project, "answer_language_strict", True)
    if not pinned_always:
        # Two situations reach here and both want the same thing.
        #
        #   no answer_language          mirror the question (the default)
        #   answer_language, not strict a HOUSE language the question beats
        #
        # In both, the language to write in is the QUESTION's, and naming it
        # is what makes that hold. MEASURED: "answer in the same language as
        # the question" is not reliably followed when the SOURCES are in
        # another language - an English question with Hindi sources came back
        # in Hindi 3 times out of 3. Naming the language scores 18/18 against
        # 12/18, and rewording the rule made it WORSE twice (4/18 emphatic,
        # 10/18 naming the script), because every mention of the foreign
        # language primes the model toward it.
        #
        # Returns None - and costs nothing - when the sources are in the
        # question's own script, where plain mirroring was measured to hold.
        # `language` then rides through as the fallback: a project that named
        # a house language gets it when the question's cannot be determined,
        # and a project that named none keeps today's instruction.
        language = cross_lingual.answer_language_for(
            project,
            question,
            sources,
            llm=llm,
            # `.add`, not the accumulator itself: usage_acc is an object with
            # an add() method here, while retrieval passes a bound method. The
            # mismatch was caught only by running the real path - the resolver
            # fails open, so it swallowed the TypeError and silently did
            # nothing, which looked exactly like the fix not working.
            on_usage=usage_acc.add if usage_acc is not None else None,
            fallback=language,
        )
    system_prompt = system_prompt_for(depth, language, disclaimer)
    user_prompt = build_user_prompt(question, sources)
    if pinned_always:
        # "Always this language" has to beat the question's own language, and
        # in the system prompt alone it does not - see enforce_language.
        user_prompt = enforce_language(user_prompt, language)
    # The key is resolved and both prompts are built from plain data - nothing
    # below this line touches the database, so the pool slot goes back before
    # the longest blocking wait in the whole request.
    release_connection(db)
    text, usage = observed_generate(
        llm,
        system_prompt,
        user_prompt,
        name="generate-answer",
        metadata={"depth": depth, "sources": len(sources)},
    )
    if usage_acc is not None:
        # Metering must never break the answer; the accumulator's add() is
        # already defensive, this guards against a caller passing junk.
        try:
            usage_acc.add(usage)
        except Exception:
            logger.debug("Usage accumulation failed", exc_info=True)
    return text


def generate_answer_stream(
    db: Session,
    project: Project,
    question: str,
    sources: list[dict],
    depth: str = "short",
    llm_fn=None,
    usage_acc=None,
):
    """Yield the answer as text deltas. Providers that implement ``generate_stream``
    (OpenAI and every OpenAI-compatible vendor) stream token by token; any other
    provider falls back to yielding the full answer once, so the same code path
    works everywhere.

    ``usage_acc`` receives numbers on BOTH branches. A streaming provider
    reports its totals through the generator's return value (delivered by
    ``yield from``), which is why the streamers had to become generators that
    return rather than merely yield. A vendor that still reports nothing -
    several OpenAI-compatible ones reject ``stream_options`` - leaves the
    counts NULL, which reads as "not measured", never as an estimate.
    """
    if llm_fn is not None:
        llm = llm_fn()
    else:
        api_key = resolver.resolve_llm_key(db, project)
        llm = get_llm(project.llm_provider, project.llm_model, api_key)
    language, disclaimer = policy_for(project)
    pinned_always = bool(language) and getattr(project, "answer_language_strict", True)
    if not pinned_always:
        # Two situations reach here and both want the same thing.
        #
        #   no answer_language          mirror the question (the default)
        #   answer_language, not strict a HOUSE language the question beats
        #
        # In both, the language to write in is the QUESTION's, and naming it
        # is what makes that hold. MEASURED: "answer in the same language as
        # the question" is not reliably followed when the SOURCES are in
        # another language - an English question with Hindi sources came back
        # in Hindi 3 times out of 3. Naming the language scores 18/18 against
        # 12/18, and rewording the rule made it WORSE twice (4/18 emphatic,
        # 10/18 naming the script), because every mention of the foreign
        # language primes the model toward it.
        #
        # Returns None - and costs nothing - when the sources are in the
        # question's own script, where plain mirroring was measured to hold.
        # `language` then rides through as the fallback: a project that named
        # a house language gets it when the question's cannot be determined,
        # and a project that named none keeps today's instruction.
        language = cross_lingual.answer_language_for(
            project,
            question,
            sources,
            llm=llm,
            # `.add`, not the accumulator itself: usage_acc is an object with
            # an add() method here, while retrieval passes a bound method. The
            # mismatch was caught only by running the real path - the resolver
            # fails open, so it swallowed the TypeError and silently did
            # nothing, which looked exactly like the fix not working.
            on_usage=usage_acc.add if usage_acc is not None else None,
            fallback=language,
        )
    system_prompt = system_prompt_for(depth, language, disclaimer)
    user_prompt = build_user_prompt(question, sources)
    if pinned_always:
        # "Always this language" has to beat the question's own language, and
        # in the system prompt alone it does not - see enforce_language.
        user_prompt = enforce_language(user_prompt, language)
    # See generate_answer - a streamed answer holds the slot even longer, for
    # as long as the client keeps reading.
    release_connection(db)
    streamer = getattr(llm, "generate_stream", None)
    if callable(streamer):
        usage = yield from observed_stream(
            llm,
            streamer,
            system_prompt,
            user_prompt,
            name="generate-answer",
            metadata={"depth": depth, "sources": len(sources), "streamed": True},
        )
        if usage_acc is not None:
            try:
                usage_acc.add(usage)
            except Exception:
                logger.debug("Usage accumulation failed", exc_info=True)
    else:
        # One blocking call - trace and meter it exactly like generate_answer.
        text, usage = observed_generate(
            llm,
            system_prompt,
            user_prompt,
            name="generate-answer",
            metadata={"depth": depth, "sources": len(sources)},
        )
        if usage_acc is not None:
            try:
                usage_acc.add(usage)
            except Exception:
                logger.debug("Usage accumulation failed", exc_info=True)
        yield text
