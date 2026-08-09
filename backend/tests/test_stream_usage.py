"""Streamed generations must report tokens - the gap that made every
`query_stream` row NULL in usage_events.

Each test drives the provider's REAL `generate_stream` against a stubbed SDK
response shaped like the vendor's, so what is verified is the extraction code
that runs in production, not a mock of it.
"""
import json
import types

import pytest

from app.providers.base import TokenUsage, stream_openai_chat


def _chunk(text=None, usage=None):
    """An OpenAI streaming chunk. The usage-bearing one has EMPTY choices."""
    choice = types.SimpleNamespace(delta=types.SimpleNamespace(content=text))
    return types.SimpleNamespace(choices=[choice] if text is not None else [],
                                 usage=usage)


def _usage(p, c):
    return types.SimpleNamespace(prompt_tokens=p, completion_tokens=c)


def drain(gen):
    """Run a generator to exhaustion, returning (text, return_value)."""
    out = []
    while True:
        try:
            out.append(next(gen))
        except StopIteration as stop:
            return "".join(out), stop.value


class TestOpenAIStyleStream:
    def test_usage_comes_from_the_final_choiceless_chunk(self):
        seen = {}

        def create(**extra):
            seen.update(extra)
            return iter([_chunk("Hel"), _chunk("lo"), _chunk(usage=_usage(120, 8))])

        text, usage = drain(stream_openai_chat(create, "gpt-4o-mini"))
        assert text == "Hello"
        assert (usage.prompt_tokens, usage.completion_tokens) == (120, 8)
        assert seen["stream_options"] == {"include_usage": True}

    def test_vendor_rejecting_stream_options_still_answers(self):
        """Several OpenAI-compatible vendors 400 on the option. The answer is
        the product; losing the token count must not lose the answer."""
        calls = []

        def create(**extra):
            calls.append(extra)
            if extra:
                raise ValueError("stream_options is not supported")
            return iter([_chunk("Hi")])

        text, usage = drain(stream_openai_chat(create, "some-vendor/model"))
        assert text == "Hi"
        assert not usage.known, "unsupported must read as unmeasured, not zero"
        assert len(calls) == 2, "should retry once without the option"

    def test_unmeasured_is_none_not_zero(self):
        def create(**extra):
            return iter([_chunk("x")])

        _, usage = drain(stream_openai_chat(create, "m"))
        assert usage.prompt_tokens is None and usage.completion_tokens is None

    def test_a_real_empty_completion_stays_zero(self):
        """0 is a measurement; only absence is None."""
        def create(**extra):
            return iter([_chunk(usage=_usage(50, 0))])

        _, usage = drain(stream_openai_chat(create, "m"))
        assert usage.completion_tokens == 0 and usage.known


class TestAnthropicStream:
    def test_final_message_supplies_usage(self):
        from app.providers.anthropic_provider import AnthropicLLM

        final = types.SimpleNamespace(usage=types.SimpleNamespace(
            input_tokens=300, output_tokens=42))

        class Stream:
            text_stream = iter(["Cla", "ude"])

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return final

        p = AnthropicLLM.__new__(AnthropicLLM)
        p.model = "claude-sonnet-4-20250514"
        p.client = types.SimpleNamespace(
            messages=types.SimpleNamespace(stream=lambda **kw: Stream()))

        text, usage = drain(p.generate_stream("sys", "user"))
        assert text == "Claude"
        assert (usage.prompt_tokens, usage.completion_tokens) == (300, 42)

    def test_missing_final_message_does_not_break_the_answer(self):
        from app.providers.anthropic_provider import AnthropicLLM

        class Stream:
            text_stream = iter(["ok"])

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                raise RuntimeError("SDK changed")

        p = AnthropicLLM.__new__(AnthropicLLM)
        p.model = "claude-x"
        p.client = types.SimpleNamespace(
            messages=types.SimpleNamespace(stream=lambda **kw: Stream()))

        text, usage = drain(p.generate_stream("s", "u"))
        assert text == "ok" and not usage.known


class TestGeminiStream:
    def test_last_reported_metadata_wins(self):
        """Gemini repeats running totals; the newest is the total."""
        from app.providers.gemini_provider import GeminiLLM

        def meta(p, c):
            return types.SimpleNamespace(
                prompt_token_count=p, candidates_token_count=c)

        chunks = [
            types.SimpleNamespace(text="a", usage_metadata=meta(10, 1)),
            types.SimpleNamespace(text="b", usage_metadata=meta(10, 2)),
        ]
        p = GeminiLLM.__new__(GeminiLLM)
        p.model = "gemini-2.5-flash"
        p._config = lambda s: None
        p.client = types.SimpleNamespace(models=types.SimpleNamespace(
            generate_content_stream=lambda **kw: iter(chunks)))

        text, usage = drain(p.generate_stream("s", "u"))
        assert text == "ab"
        assert (usage.prompt_tokens, usage.completion_tokens) == (10, 2)


class TestOllamaStream:
    def test_done_line_supplies_counts(self, monkeypatch):
        from app.providers import ollama_provider as mod

        lines = [
            json.dumps({"message": {"content": "hi"}}),
            json.dumps({"done": True, "prompt_eval_count": 77, "eval_count": 5}),
        ]

        class Resp:
            def raise_for_status(self):
                pass

            def iter_lines(self):
                return iter(lines)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(mod.httpx, "stream", lambda *a, **kw: Resp())
        p = mod.OllamaLLM.__new__(mod.OllamaLLM)
        p.model = "llama3"

        text, usage = drain(p.generate_stream("s", "u"))
        assert text == "hi"
        assert (usage.prompt_tokens, usage.completion_tokens) == (77, 5)


class TestEveryStreamingProviderReturnsUsage:
    """A provider that streams text but returns None would silently reinstate
    the NULL columns this change exists to fill."""

    @pytest.mark.parametrize("module_name", [
        "openai_provider", "openai_compat", "sarvam_provider",
        "anthropic_provider", "gemini_provider", "ollama_provider",
    ])
    def test_generate_stream_returns_a_value(self, module_name):
        import ast
        import pathlib

        src = pathlib.Path(f"app/providers/{module_name}.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        streams = [n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "generate_stream"]
        assert streams, f"{module_name} has no generate_stream"
        for fn in streams:
            returns = [n for n in ast.walk(fn)
                       if isinstance(n, ast.Return) and n.value is not None]
            assert returns, (
                f"{module_name}.generate_stream yields text but returns no "
                "usage - streamed rows would be NULL again")
