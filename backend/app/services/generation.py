import logging

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from ..models import Project
from ..providers import resolver
from ..providers.registry import get_llm

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


def system_prompt_for(depth: str) -> str:
    """Pick the grounding prompt for the detected answer depth."""
    return LONG_SYSTEM_PROMPT if depth == "long" else SHORT_SYSTEM_PROMPT


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
) -> str:
    # query.py passes its per-request LLM getter (key resolved at most once)
    # as ``llm_fn``; standalone callers omit it and resolution happens here.
    if llm_fn is not None:
        llm = llm_fn()
    else:
        api_key = resolver.resolve_llm_key(db, project)
        llm = get_llm(project.llm_provider, project.llm_model, api_key)
    system_prompt = system_prompt_for(depth)
    user_prompt = build_user_prompt(question, sources)
    # The key is resolved and both prompts are built from plain data - nothing
    # below this line touches the database, so the pool slot goes back before
    # the longest blocking wait in the whole request.
    release_connection(db)
    return llm.generate(system_prompt, user_prompt)


def generate_answer_stream(
    db: Session,
    project: Project,
    question: str,
    sources: list[dict],
    depth: str = "short",
    llm_fn=None,
):
    """Yield the answer as text deltas. Providers that implement ``generate_stream``
    (OpenAI and every OpenAI-compatible vendor) stream token by token; any other
    provider falls back to yielding the full answer once, so the same code path
    works everywhere."""
    if llm_fn is not None:
        llm = llm_fn()
    else:
        api_key = resolver.resolve_llm_key(db, project)
        llm = get_llm(project.llm_provider, project.llm_model, api_key)
    system_prompt = system_prompt_for(depth)
    user_prompt = build_user_prompt(question, sources)
    # See generate_answer - a streamed answer holds the slot even longer, for
    # as long as the client keeps reading.
    release_connection(db)
    streamer = getattr(llm, "generate_stream", None)
    if callable(streamer):
        yield from streamer(system_prompt, user_prompt)
    else:
        yield llm.generate(system_prompt, user_prompt)
