"""Every LLM provider must report what it consumed.

WHY THIS EXISTS: `usage_events.prompt_tokens` and `completion_tokens` have been
in the schema since migration 0016 and were NULL for every row ever written -
not because of a bug, but because `LLMProvider.generate()` returned a bare `str`
and each implementation threw the SDK's usage object away. Nothing failed.
Nothing logged. The columns just stayed empty, and Phase 9 billing had nothing
to bill on.

`base.call_llm()` deliberately TOLERATES an object that only implements
`generate` - every test stub in this suite does, and forcing ~13 of them to grow
a method they do not care about would be churn for nothing. That tolerance is
exactly how a real provider could silently go back to reporting nothing, which
is what the first test here prevents.
"""
import inspect

import pytest

from app.providers import base
from app.providers.base import (
    TokenUsage,
    call_llm,
    usage_from_anthropic,
    usage_from_gemini,
    usage_from_ollama,
    usage_from_openai,
)

# Every concrete LLM class the registry can hand out. Import lazily inside the
# test so a missing optional SDK cannot break collection of the whole file.
PROVIDER_CLASSES = [
    ("app.providers.openai_provider", "OpenAILLM"),
    ("app.providers.anthropic_provider", "AnthropicLLM"),
    ("app.providers.gemini_provider", "GeminiLLM"),
    ("app.providers.openai_compat", "CompatLLM"),
    ("app.providers.sarvam_provider", "SarvamLLM"),
    ("app.providers.ollama_provider", "OllamaLLM"),
]


def _load(module_name: str, class_name: str):
    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, class_name, None)


class TestEveryProviderReportsUsage:
    def test_the_class_list_is_not_stale(self):
        """Guards the guard: a renamed class would silently shrink coverage."""
        missing = [
            f"{m}.{c}" for m, c in PROVIDER_CLASSES if _load(m, c) is None
        ]
        assert missing == [], f"provider classes not found: {missing}"

    @pytest.mark.parametrize("module_name,class_name", PROVIDER_CLASSES)
    def test_provider_implements_generate_with_usage(self, module_name, class_name):
        cls = _load(module_name, class_name)
        assert hasattr(cls, "generate_with_usage"), (
            f"{class_name} has no generate_with_usage - call_llm() will fall "
            "back to generate() and report NO tokens, silently, for every "
            "request routed to this provider"
        )

    @pytest.mark.parametrize("module_name,class_name", PROVIDER_CLASSES)
    def test_generate_delegates_rather_than_duplicating(self, module_name, class_name):
        """`generate` must call `generate_with_usage`, not re-issue its own
        request. Two independent code paths to the same vendor is how one of
        them quietly stops being maintained - and it would double-charge."""
        cls = _load(module_name, class_name)
        src = inspect.getsource(cls.generate)
        assert "generate_with_usage" in src, (
            f"{class_name}.generate does not delegate to generate_with_usage"
        )


class TestUsageExtractors:
    """Each vendor names the fields differently. Getting one wrong yields NULL
    for that provider only - invisible unless you happen to use it."""

    class _Obj:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def test_openai_shape(self):
        resp = self._Obj(usage=self._Obj(prompt_tokens=11, completion_tokens=4))
        assert usage_from_openai(resp, "m") == TokenUsage(11, 4, "m")

    def test_anthropic_uses_input_output_names(self):
        resp = self._Obj(usage=self._Obj(input_tokens=8, output_tokens=2))
        assert usage_from_anthropic(resp, "m") == TokenUsage(8, 2, "m")

    def test_gemini_uses_usage_metadata_and_candidates(self):
        resp = self._Obj(
            usage_metadata=self._Obj(prompt_token_count=5, candidates_token_count=9)
        )
        assert usage_from_gemini(resp, "m") == TokenUsage(5, 9, "m")

    def test_ollama_reads_the_json_body(self):
        assert usage_from_ollama(
            {"prompt_eval_count": 7, "eval_count": 3}, "m"
        ) == TokenUsage(7, 3, "m")

    @pytest.mark.parametrize(
        "extractor,payload",
        [
            (usage_from_openai, object()),
            (usage_from_anthropic, object()),
            (usage_from_gemini, object()),
            (usage_from_ollama, "not-a-dict"),
        ],
    )
    def test_a_missing_usage_object_never_raises(self, extractor, payload):
        """Metering must never break generation. The answer is the product; the
        token count is bookkeeping. A vendor that renames a field or omits usage
        yields None, not an exception in the middle of a user's request."""
        result = extractor(payload, "m")
        assert result.prompt_tokens is None
        assert result.completion_tokens is None

    def test_a_string_count_is_rejected_not_coerced(self):
        """A vendor returning "11" must read as unmeasured rather than becoming
        a number that looks measured."""
        resp = self._Obj(usage=self._Obj(prompt_tokens="11", completion_tokens=None))
        assert usage_from_openai(resp, "m").prompt_tokens is None

    def test_booleans_are_not_counts(self):
        """bool is an int in Python - True would otherwise become 1 token."""
        resp = self._Obj(usage=self._Obj(prompt_tokens=True, completion_tokens=False))
        assert usage_from_openai(resp, "m").prompt_tokens is None


class TestUsageArithmetic:
    """One /query makes up to three model calls - condense, decompose, then
    clarify OR synthesise - and the billing row wants the total."""

    def test_sums_across_calls(self):
        assert TokenUsage(10, 5) + TokenUsage(3, 2) == TokenUsage(13, 7)

    def test_an_unmeasured_call_does_not_erase_a_measured_one(self):
        """The dangerous direction: `None` must not zero the running total, or
        one provider without usage would wipe the whole request's cost."""
        assert (TokenUsage() + TokenUsage(10, 5)).prompt_tokens == 10
        assert (TokenUsage(10, 5) + TokenUsage()).prompt_tokens == 10

    def test_nothing_measured_stays_none_not_zero(self):
        """Zero is a real answer (an empty completion). Collapsing it with
        'we did not measure' makes the billing table lie."""
        total = TokenUsage() + TokenUsage()
        assert total.prompt_tokens is None
        assert total.known is False

    def test_zero_is_preserved_as_a_real_measurement(self):
        assert TokenUsage(0, 0).known is True


class TestCallLlmFallback:
    def test_a_stub_without_usage_still_works(self):
        class Stub:
            model = "stub"

            def generate(self, system, user):
                return "text"

        text, usage = call_llm(Stub(), "s", "u")
        assert text == "text"
        assert usage.known is False, "a stub must not fabricate token counts"
        assert usage.model == "stub"

    def test_a_real_provider_is_preferred(self):
        class Real:
            model = "real"

            def generate(self, system, user):  # pragma: no cover - not taken
                raise AssertionError("call_llm used generate instead of the usage path")

            def generate_with_usage(self, system, user):
                return "text", TokenUsage(4, 2, "real")

        text, usage = call_llm(Real(), "s", "u")
        assert (text, usage) == ("text", TokenUsage(4, 2, "real"))

    def test_base_exports_what_the_services_import(self):
        """A rename here breaks metering everywhere at once."""
        for name in (
            "TokenUsage",
            "call_llm",
            "usage_from_openai",
            "usage_from_anthropic",
            "usage_from_gemini",
            "usage_from_ollama",
        ):
            assert hasattr(base, name), f"providers.base lost {name}"
