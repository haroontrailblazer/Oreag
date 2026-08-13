"""The last-chance relaxed pass, borrowed from RAGFlow.

RAGFlow drops its similarity floor (0.2 -> 0.17) when a retrieval pass comes
back empty rather than escalating straight away. Oreag had no equivalent: a best
source scoring 0.19 against a floor of 0.20 produced a clarifying question about
material the system had already found, and widening top_k - the only thing the
loop did - cannot fix that, because the problem was the bar and not the number
of candidates.
"""
from app.services import agentic


def _sources(*sims):
    return [
        {
            "content": f"c{i}",
            "filename": "f.md",
            "similarity": s,
            "chunk_index": i,
            "page_number": None,
        }
        for i, s in enumerate(sims)
    ]


def _gather(sims, *, min_similarity=0.2, min_strong=1, max_rounds=1):
    clarified = []

    def clarify(q):
        clarified.append(q)
        return ["what exactly do you mean?"]

    ctx = agentic.gather_context(
        question="why do people never feel satisfied?",
        retrieve_fn=lambda q, k: _sources(*sims),
        plan_fn=lambda q: [q],
        clarify_fn=clarify,
        top_k=5,
        min_similarity=min_similarity,
        min_strong=min_strong,
        max_rounds=max_rounds,
    )
    return ctx, clarified


class TestRelaxedFallback:
    def test_a_near_miss_now_answers_instead_of_interrupting(self):
        """0.19 against a 0.20 floor: found it, was about to ask anyway."""
        ctx, clarified = _gather([0.19])
        assert ctx.needs_clarification is False
        assert clarified == [], "should not have paid for a clarify call"
        assert ctx.sources

    def test_genuinely_absent_material_still_reaches_a_human(self):
        """The threshold still means something - this is the whole point."""
        ctx, clarified = _gather([0.02])
        assert ctx.needs_clarification is True
        assert clarified, "a real miss must still clarify"

    def test_the_relaxed_floor_is_not_a_free_pass(self):
        """Just below the relaxed floor is still a miss."""
        # floor 0.20 -> relaxed 0.17; 0.16 must not qualify.
        ctx, _ = _gather([0.16])
        assert ctx.needs_clarification is True

    def test_min_strong_is_still_enforced_at_the_relaxed_floor(self):
        """Relaxing the bar must not also relax how many sources clear it."""
        ctx, _ = _gather([0.19, 0.02], min_strong=2)
        assert ctx.needs_clarification is True

    def test_a_normal_pass_is_unaffected(self):
        """Comfortably-grounded questions take the same path as before."""
        ctx, clarified = _gather([0.8, 0.6])
        assert ctx.needs_clarification is False
        assert clarified == []

    def test_the_relaxation_is_small(self):
        """A large relaxation would answer from material the system does not
        believe in, which is the failure the threshold exists to prevent."""
        assert 0.8 <= agentic.RELAXED_SIMILARITY_RATIO < 1.0
