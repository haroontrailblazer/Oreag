from ..models import Project
from ..providers.registry import get_llm

SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions strictly from the provided "
    "context. If the context does not contain enough information to answer, say you "
    "don't know — never invent facts. Cite the context blocks you used as [1], [2], "
    "etc. Keep answers concise and factual."
)


def build_user_prompt(question: str, sources: list[dict]) -> str:
    context = "\n\n".join(
        f"[{i + 1}] {s['filename']} (page {s['page_number']}):\n{s['content']}"
        for i, s in enumerate(sources)
    )
    return f"Context:\n{context}\n\nQuestion: {question}"


def generate_answer(project: Project, question: str, sources: list[dict]) -> str:
    llm = get_llm(project.llm_provider, project.llm_model)
    return llm.generate(SYSTEM_PROMPT, build_user_prompt(question, sources))
