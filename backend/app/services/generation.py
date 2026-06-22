from sqlalchemy.orm import Session

from ..models import Project
from ..providers import resolver
from ..providers.registry import get_llm

# A focused question wants a short, factual answer — and should still refuse
# rather than invent when the context truly lacks the answer.
SHORT_SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions strictly from the provided "
    "context. If the context does not contain enough information to answer, say you "
    "don't know — never invent facts. Cite the context blocks you used as [1], [2], "
    "etc. Keep answers concise and factual."
)

# A broad, multi-part (exam-style) question wants a long, structured answer. The
# agentic loop has already gathered a wide context, so the model should write the
# full answer it can support — and, crucially, NOT bail with "I don't know" when
# the context is only partial (that refusal is what made big questions return
# nothing). Genuine gaps are stated, not used as an excuse to refuse outright.
LONG_SYSTEM_PROMPT = (
    "You are an expert assistant answering an exam-style question that calls for a "
    "thorough, well-structured answer. Use ALL of the relevant information in the "
    "provided context and write a comprehensive answer: open with a short overview, "
    "then cover each part under clear headings or numbered points, and finish with "
    "a brief summary where it helps. Ground every claim in the context and cite the "
    "blocks you used as [1], [2], etc. If the context covers the topic only "
    "partially, answer as fully as the context allows and state plainly which parts "
    "are not covered — do NOT refuse to answer outright."
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
