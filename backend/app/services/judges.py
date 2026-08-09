"""LLM-as-judge scoring for answered queries.

WHAT THIS ANSWERS THAT METERING CANNOT

Tokens, cost and latency say the system was fast or expensive. They cannot say
the answer was WRONG - that the model asserted something the retrieved sources
never supported, or that retrieval handed it chunks about the wrong topic
entirely. Those are the two failure modes that matter in a RAG product, and
neither leaves a trace in usage_events.

WHOSE MONEY THIS SPENDS

A judge call is a real model call on the project's OWN provider key. That makes
this different from every other observability feature here, all of which are
free to the user. Three consequences, all deliberate:

  * OFF by default (`langfuse_judge_enabled`). Nobody's bill grows because
    they upgraded.
  * SAMPLED when on (5% by default). Judging every request would roughly
    double generation spend, which is absurd for a feature meant to help
    control cost.
  * METERED like anything else, under the "judge" endpoint - so it appears on
    the Usage page as its own line rather than quietly inflating "query".

WHY SCORES GO TO LANGFUSE AND NOT A LOCAL TABLE

Scores attach to the trace they judge, so a bad score is one click from the
question, the retrieved chunks and the answer that earned it. Stored locally
they would be numbers with nothing to look at.

Everything here is best-effort and runs AFTER the response has been sent. A
judge that fails, times out or returns nonsense must never affect the answer
the user already received.
"""
import json
import logging
import random
import re

from ..config import settings
from ..providers import resolver
from ..providers.base import ProviderUnavailableError, TokenUsage, call_llm
from ..providers.registry import get_llm
from .tracing import client

logger = logging.getLogger(__name__)

# Asks for the two things retrieval-augmented generation actually gets wrong,
# and nothing else. A judge with ten criteria produces ten mediocre numbers.
JUDGE_SYSTEM_PROMPT = """\
You are evaluating one answer produced by a retrieval-augmented system.

Score two things, each from 0.0 to 1.0:

groundedness - is every claim in the answer supported by the provided sources?
  1.0 = fully supported. 0.0 = the answer asserts things the sources do not
  say. An answer that correctly says it cannot find something scores 1.0:
  refusing to guess is grounded behaviour, not a failure.

relevance - do the retrieved sources actually address the question?
  1.0 = the sources are on-topic and sufficient. 0.0 = retrieval returned
  material about something else. Judge the SOURCES here, not the answer -
  this is what separates a retrieval problem from a generation problem.

Reply with ONLY a JSON object, no prose and no code fence:
{"groundedness": <float>, "relevance": <float>, "comment": "<one short sentence>"}
"""

_SCORE_KEYS = ("groundedness", "relevance")


def should_judge() -> bool:
    """Sampling decision for one request. Cheap, and short-circuits when off."""
    if not settings.langfuse_judge_enabled:
        return False
    rate = settings.langfuse_judge_sample_rate
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    return random.random() < rate


def _parse(raw: str) -> dict | None:
    """Pull the JSON object out of a judge reply.

    Tolerant on purpose: models wrap JSON in code fences, add a preamble, or
    emit trailing prose no matter how firmly the prompt says not to. A judge
    that returns a usable score wrapped in noise should count as a success -
    the alternative is silently discarding most of the scores that were paid
    for.
    """
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except Exception:
            return None
    if not isinstance(parsed, dict):
        return None

    out: dict = {}
    for key in _SCORE_KEYS:
        value = parsed.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        # Clamp rather than reject: a model that answers 1.2 meant "very good",
        # and throwing the score away would lose more than it protects.
        out[key] = max(0.0, min(1.0, float(value)))
    if not out:
        return None
    comment = parsed.get("comment")
    if isinstance(comment, str) and comment.strip():
        out["comment"] = comment.strip()[:500]
    return out


def judge_answer(
    db, project, *, question: str, answer: str, sources: list[dict], trace_id: str
) -> TokenUsage | None:
    """Score one answered query and attach the result to its Langfuse trace.

    Returns what the judge itself consumed, so the caller can meter it. Returns
    None when nothing was judged - disabled, unsampled, no trace to attach to,
    or a failure at any point.

    Never raises. This runs after the user already has their answer.
    """
    lf = client()
    if lf is None or not trace_id or not sources:
        return None

    try:
        api_key = resolver.resolve_llm_key(db, project)
        llm = get_llm(project.llm_provider, project.llm_model, api_key)
    except (ProviderUnavailableError, Exception):
        logger.debug("No usable LLM for judging", exc_info=True)
        return None

    # The sources are truncated hard. A judge prompt carrying twenty full
    # chunks can cost more than the answer it is judging, which would make the
    # evaluation more expensive than the thing evaluated.
    excerpt = "\n\n".join(
        f"[{i + 1}] {s.get('filename', '?')}: {str(s.get('content', ''))[:600]}"
        for i, s in enumerate(sources[:8])
    )
    user_prompt = (
        f"Question:\n{question}\n\n"
        f"Sources:\n{excerpt}\n\n"
        f"Answer:\n{answer[:4000]}"
    )

    try:
        text, usage = call_llm(llm, JUDGE_SYSTEM_PROMPT, user_prompt)
    except Exception:
        logger.debug("Judge call failed", exc_info=True)
        return None

    scores = _parse(text)
    if scores is None:
        logger.debug("Judge returned no parseable scores")
        return usage  # still metered: the call was made and billed

    comment = scores.pop("comment", None)
    for name, value in scores.items():
        try:
            lf.create_score(
                trace_id=trace_id,
                name=name,
                value=value,
                data_type="NUMERIC",
                comment=comment,
            )
        except Exception:
            logger.debug("Could not attach score %s", name, exc_info=True)
    try:
        lf.flush()
    except Exception:
        logger.debug("Score flush failed", exc_info=True)
    return usage


def ensure_score_configs() -> None:
    """Register the two score definitions with Langfuse, once per process.

    Without a config a score still records, but the dashboard shows it as an
    untyped number with no range - so it cannot be charted or filtered
    sensibly. Registering the 0..1 bounds is what makes the scores usable in
    the UI the user is meant to read them in.
    """
    lf = client()
    if lf is None:
        return
    import httpx

    base = (settings.langfuse_base_url or "").rstrip("/")
    auth = (settings.langfuse_public_key or "", settings.langfuse_secret_key or "")
    if not base or not all(auth):
        return
    for name, description in (
        ("groundedness", "Every claim in the answer is supported by the sources."),
        ("relevance", "The retrieved sources actually address the question."),
    ):
        try:
            httpx.post(
                f"{base}/api/public/score-configs",
                auth=auth,
                timeout=15,
                json={
                    "name": name,
                    "dataType": "NUMERIC",
                    "minValue": 0,
                    "maxValue": 1,
                    "description": description,
                },
            )
        except Exception:
            # A duplicate is a 409 and is exactly as fine as a 200.
            logger.debug("Score config %s not created", name, exc_info=True)


def schedule(project_id, *, question: str, answer: str, sources: list[dict],
             trace_id: str) -> None:
    """Run a judge pass on a daemon thread, with its OWN database session.

    A thread rather than the caller's context, and a fresh session rather than
    the request's, because this has to work identically from BOTH query routes:

      * `/query` returns and its response is done;
      * `/query/stream` is still holding an open SSE connection, and blocking
        in the generator's `finally` would keep that connection open while an
        evaluation the client is not waiting for runs.

    Sharing one mechanism means there is one lifetime to reason about instead
    of two. Fire-and-forget: nothing observes the result except Langfuse.
    """
    import threading

    def run() -> None:
        from ..db import SessionLocal
        from ..models import Project
        from .usage import record_usage

        db = SessionLocal()
        try:
            project = db.get(Project, project_id)
            if project is None:
                return
            usage = judge_answer(
                db, project, question=question, answer=answer,
                sources=sources, trace_id=trace_id,
            )
            if usage is not None:
                record_usage(
                    db, project=project, api_key_id=None,
                    endpoint="judge", usage=usage,
                )
        except Exception:
            logger.debug("Judge task failed", exc_info=True)
        finally:
            db.close()

    threading.Thread(target=run, name="oreag-judge", daemon=True).start()
