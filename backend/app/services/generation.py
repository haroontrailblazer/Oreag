from sqlalchemy.orm import Session

from ..models import Project
from ..providers import resolver
from ..providers.registry import get_llm

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


def generate_answer(
    db: Session,
    project: Project,
    question: str,
    sources: list[dict],
    depth: str = "short",
) -> str:
    api_key = resolver.resolve_llm_key(db, project)
    llm = get_llm(project.llm_provider, project.llm_model, api_key)
    return llm.generate(
        system_prompt_for(depth), build_user_prompt(question, sources)
    )


def generate_answer_stream(
    db: Session,
    project: Project,
    question: str,
    sources: list[dict],
    depth: str = "short",
):
    """Yield the answer as text deltas. Providers that implement ``generate_stream``
    (OpenAI and every OpenAI-compatible vendor) stream token by token; any other
    provider falls back to yielding the full answer once, so the same code path
    works everywhere."""
    api_key = resolver.resolve_llm_key(db, project)
    llm = get_llm(project.llm_provider, project.llm_model, api_key)
    system_prompt = system_prompt_for(depth)
    user_prompt = build_user_prompt(question, sources)
    streamer = getattr(llm, "generate_stream", None)
    if callable(streamer):
        yield from streamer(system_prompt, user_prompt)
    else:
        yield llm.generate(system_prompt, user_prompt)
