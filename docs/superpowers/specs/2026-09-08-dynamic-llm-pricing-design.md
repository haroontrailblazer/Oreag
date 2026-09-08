# Dynamic LLM pricing — design spec

# `MODEL_PRICES_USD_PER_MTOK` stops being the authority and becomes the last fallback: a community-maintained feed, refreshed by the daemon that already runs, priced through a **provider-scoped** lookup, so a price change or a new model needs no code edit — and no hand-written table can go stale without anyone noticing again.

## Why

`registry.py` says it plainly in its own comment: the table is "hand-written and
dated", and `scripts/reconcile_pricing.py` says "there is no test that can catch
it - the table IS the expected value."

That is not hypothetical. Measured on 2026-09-08 against LiteLLM's feed, with a
provider-scoped lookup, **six of the 29 priced ids are wrong today**:

| model | our table | feed | |
|---|---|---|---|
| `claude-sonnet-5` | 3.00 / 15.00 | **2.00 / 10.00** | Langfuse's table agrees with the feed, not us |
| `grok-4` | 3.00 / 15.00 | **1.25 / 2.50** | we overstate output ~6x |
| `deepseek-v4-flash` | 0.14 / 0.28 | **0.44 / 1.32** | we understate ~4.7x |
| `deepseek-v4-pro` | 0.435 / 0.87 | **1.32 / 3.96** | we understate ~4.5x |
| `openai/gpt-oss-120b` (groq) | 0.15 / 0.75 | **0.15 / 0.60** | |
| `meta-llama/Llama-3.3-70B-Instruct-Turbo` (together) | 0.88 / 0.88 | **1.04 / 1.04** | |

Coverage is the other half. Of 29 priced ids the feed has **29**; of the 56
selectable `CATALOG["llm"]` ids we price 29 and the feed prices **21 of the
remaining 27**; of 22 catalog embedders we price **3** and the feed prices
**13** (13 of the 17 that are not local, and the 5 local ones correctly have no
price anywhere). Every one of the 13 ids that Langfuse cannot price at all is
priced by the feed.

Concretely: the `unpriced_models` caveat added in `5a41ebe` exists to admit that
the spend total is short. This change is what makes it mostly stop firing.

## Not a billing change

`cost_usd` is a figure shown to a BYOK customer about their own provider spend.
Nobody is invoiced from it. That decides the shape: the feed is applied
automatically with no staging or approval gate, because a wrong value is a wrong
chart for a few hours and the next refresh corrects it. **If Phase 9 ever bills
from this column, this design must be revisited** — an external feed writing
invoices needs an approval gate and immutable history, and neither is here.

## No dated price table, and why

Migration `0027` fixed the doctrine: cost is computed at write time and frozen
in the row, "a later price change must not silently rewrite history". So the
only question this subsystem answers is *what is the best-known price right
now*. There is nothing to date, nothing to migrate, no table.

That is what makes the whole thing a module and a daemon hook rather than a
schema change.

## The source, and the fallback chain

```
cost_breakdown(model, usage, provider)
   1. pricing.lookup(model, provider)   live feed, refreshed every N hours
   2. bundled snapshot                  backend/app/providers/prices.json, in git
   3. MODEL_PRICES_USD_PER_MTOK         hand-verified, last resort
   4. None                              honest gap - unchanged doctrine
```

**Primary: LiteLLM `model_prices_and_context_window.json`** (3818 entries,
~2.3 MB, no auth). Chosen over the two alternatives on coverage: OpenRouter's
`/api/v1/models` only knows models OpenRouter fronts, and Langfuse's
`/api/public/models` has 182 definitions and misses 13 of ours — the very gap
that motivated `5a41ebe`. LiteLLM also carries `cache_read_input_token_cost`
and `cache_creation_input_token_cost`, which nothing else does uniformly.

**Layer 2 is what makes a cold Render boot correct.** The snapshot is generated
by a script and committed, so a deploy with a dead feed still prices everything
the last refresh knew. It also gives the audit trail a runtime fetch cannot:
every price move shows up in a diff.

**Layer 3 stays** because it is the only thing that works with no network *and*
no snapshot, and because it is human-verified. It stops being the authority.

## Provider-scoped lookup — the part that must not be got wrong

The feed is keyed by vendor-prefixed ids (`groq/llama-3.3-70b-versatile`,
`together_ai/meta-llama/...`, `fireworks_ai/accounts/fireworks/models/...`), and
**the same model id has different prices on different vendors**. A naive
"match the id, any vendor" scan was measured and it is dangerous:

| our id | naive match | correct, provider-scoped |
|---|---|---|
| `accounts/fireworks/models/deepseek-v3` | `azure_ai/deepseek-v3` ❌ | `fireworks_ai/...` $0.90 ✅ |
| `meta-llama/Llama-3.3-70B-Instruct-Turbo` | `deepinfra/...` $0.10 ❌ | `together_ai/...` $1.04 ✅ |
| `anthropic/claude-sonnet-4.5` | `github_copilot/...` (null price) ❌ | `openrouter/...` $3/$15 ✅ |

An 8x error from the wrong vendor — the same BYOK trap the cost work already
hit once. So:

- Index the feed by `(litellm_provider, id)` with an explicit Oreag→LiteLLM
  provider map: `together`→`together_ai`, `fireworks`→`fireworks_ai`,
  `gemini`→`gemini|vertex_ai`, `azure`→`azure|azure_ai`, `cohere`→
  `cohere|cohere_chat`, and so on.
- Within the correct vendor only, try exact id, then id without a vendor
  prefix, then prefixed.
- **If the provider is unknown, or that vendor has no entry, return `None`.**
  Never fall through to another vendor. This is the existing `registry.py` rule
  restated: "a guessed price is a silently wrong invoice, which is strictly
  worse than an honest gap." An unmatched model keeps returning NULL and keeps
  being named in `unpriced_models`.

## How the provider reaches the pricer

`cost_for(model, usage)` has no provider today and cannot do the above without
one. Two facts make this cheap:

- `get_llm(provider, model, api_key)` (registry.py:707) already receives the
  canonical provider string, is `@lru_cache`d with it as the first key element,
  and no LLM class defines `__slots__`. One line there stamps `llm.provider`.
- `TokenUsage` gains `provider: str = ""`, appended with a default exactly as
  `reasoning_tokens` was in `5a41ebe` — no positional construction breaks.

Both consumers already hold it:

- `services/usage.py::record_usage` → `project.llm_provider` /
  `project.embedding_provider`
- `services/tracing.py::_usage_fields` → `usage.provider`

## Refresh, validation, failure

Rides `services/maintenance.py`, which already runs one daemon thread from the
app lifespan on `settings.maintenance_interval_seconds`, plus one non-blocking
refresh at startup. Per-instance caches; no coordination is needed for
read-only data and no instance has to win a race.

New settings: `pricing_feed_enabled` (default true), `pricing_feed_url`,
`pricing_refresh_interval_seconds`.

**A payload replaces the cache only after it validates**: a minimum entry count,
required fields present, no negative or absurd rates, and a handful of known
anchors still resolving (`gpt-4o-mini` at $0.15/$0.60). A truncated or garbage
fetch keeps the previous cache. Fetch failure logs and continues — pricing never
raises, the same contract `tracing.py` holds.

**Divergence is logged, not silently absorbed.** When the feed and layer 3
disagree by more than 20% for a model, log it at WARNING. That is how a bad
feed becomes visible instead of quietly repricing the dashboard.

## Files

| file | change |
|---|---|
| `backend/app/providers/pricing.py` | **new** — fetch, validate, index, `lookup(model, provider)` |
| `backend/app/providers/prices.json` | **new** — committed snapshot (layer 2) |
| `backend/app/providers/registry.py` | `cost_breakdown` / `embedding_cost_for` take `provider`, consult `pricing` first; `get_llm` stamps `llm.provider` |
| `backend/app/providers/base.py` | `TokenUsage.provider` |
| `backend/app/services/usage.py` | pass `project.llm_provider` / `embedding_provider` |
| `backend/app/services/tracing.py` | pass `usage.provider` |
| `backend/app/services/maintenance.py` | call `pricing.refresh()` in the sweep |
| `backend/app/config.py` | three settings |
| `scripts/refresh_prices.py` | **new** — regenerate the snapshot |

## Testing

Against a committed fixture slice of the feed, never the network.

- **Provider scoping is the headline test.** The three wrong-vendor matches in
  the table above become explicit regression cases: `together` must not resolve
  to `deepinfra`, `fireworks` must not resolve to `azure_ai`.
- Fallback chain: feed hit; feed miss → snapshot; both miss → layer 3; all miss
  → `None` (and NOT 0).
- Validation rejects a truncated payload, a negative rate, and a payload whose
  anchors have vanished — and the previous cache survives each.
- `refresh()` never raises: no network, malformed JSON, HTTP 500.
- An unknown provider returns `None` rather than any price.

## Out of scope

- **Cached-token rates.** The feed carries them and `PriceEntry` will store
  them, but nothing uses them until `TokenUsage` captures cached-token *counts*
  — measured as unreachable on current traffic (0 of 676 live generations carry
  a cache key).
- **Per-account negotiated rates.** No feed knows a committed-use discount, an
  enterprise agreement, Azure PTU or OpenRouter's markup. This gets the list
  price right; it cannot get *your* price right. The "Estimated cost" label and
  its "at list prices" footer, added in `5a41ebe`, stay true and stay necessary.
- **Sub-project #2 — dynamic catalog.** Auto-adding models to `CATALOG` and
  probing embedder dimensions. Independent of this, riskier, its own spec.
  Two constraints already agreed and recorded here so they are not lost:
  1. Auto-added models must land in `embedder_advice._TIERS` as tier
     `"unknown"` **explicitly**, never by omission —
     `test_embedder_advice.py::test_every_catalog_model_has_a_tier` failing on
     an auto-added model is that test working, not an obstacle. Silence and
     unknown must not be the same state, exactly as an unpriced model reports
     NULL and gets named rather than showing $0.00.
  2. `dimension_options` (Matryoshka) is **not discoverable**. A probe gives
     the native width by measuring the returned vector; nothing reveals whether
     a model truncates safely. Auto-added embedders therefore get an empty
     `dimension_options`, which is what keeps `send_dimensions` False in
     `get_embedder` — the Voyage entry in `CATALOG` documents why that matters.

## What this does not fix

The app-vs-Langfuse gap is already closed by `5a41ebe` (`cost_details` makes
Oreag authoritative for every id it prices). This change widens *how many ids it
prices*, which shrinks the residue where Langfuse still prices from its own
table. It does not touch the app-vs-**invoice** gap for anything with a
non-list rate, and nothing in a token-price table ever will.
