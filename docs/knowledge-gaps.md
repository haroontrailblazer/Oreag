# Knowledge gaps

Open **Gaps** in the dashboard sidebar, or choose **Review knowledge
gaps** from a project's Health detail. The inbox turns query history and answer
feedback into a review workflow: inspect questions, update documents, add a
regression case to the existing evaluator, and record the outcome.

## Grouping and evidence

Questions are grouped within a single project when wording matches after Unicode
NFC normalization, case folding, whitespace normalization, and removal of trailing
question/exclamation marks. The stable group key preserves numbers, negation,
internal punctuation, and word order. Paraphrases remain separate; this is not
semantic topic clustering and it does not call an LLM or embedding provider.

A query is flagged when its current feedback is **not helpful**, or when it was
answered without a cache hit and its measured retrieval similarity is below
**0.35**. This fixed review heuristic does not change project answer thresholds.
Missing similarity is unknown, never zero; cached similarity does not count as
fresh retrieval. Similarity is not an answer-accuracy score. Helpful and unrated
matching queries remain visible as context. A query with both signals is counted
once in **Flagged queries** and in each applicable signal count.

Filter by project, the last **7/30/90 days**, status, question text, or repeated
questions only (at least two matching queries). Lists show open groups first,
then most flagged queries, recurrence, and recency. Summary totals use the project
and time scope before status, text, or recurrence filtering.

Each report scans at most the latest **5,000 queries** in its scope and labels
truncated history. Query creation time determines the window; future timestamps
are excluded. A group's detail scans the selected project separately, so it may
show more evidence than a truncated account list. Groups and evidence paginate
in pages of 25. Evidence is flagged first, then newest; query IDs remain strings
to preserve PostgreSQL bigint precision in JavaScript.

## Review and resolution

Open a group to inspect its full question, feedback notes, counts, and individual
queries. **Review documents** opens the project's Files tab. **Test in Playground**
opens Playground, where Evaluator is available. **Add to test set** on an evidence
query uses the existing evaluator flow to save a regression case.

Save a review note (up to 2,000 characters), **Close review**, or **Reopen gap**.
Review state is saved per project and group, independently of reporting windows.
Closing a review dismisses the issue without testing it and displays **Closed review**.
To verify a fix, select affected questions in **Verify fix**, add expected answer
text or a source, and run the checks. Review the returned answers, choose **Use for
resolution**, then **Resolve with verification**. Every selected check must pass
against current documents, settings, and gap evidence. The outcome displays
**Resolved with checks**, with the saved questions, answers, and checks available
when you reopen its details, including after the run is archived.

When a previous completed verification used identical questions, checks, and
configurations, the results show the change in each check. **Previously failed;
now passing** requires an actual failing earlier test. A first passing run records
current behavior; it does not establish improvement or certify overall answer
accuracy. A manually closed review can still have a passing verification attached.
New flagged queries or negative feedback added/updated after the resolution cause
the group to appear as **New evidence** and need review again. Healthy traffic
alone does not reopen it. The previous review note remains available.

Writes include both the review revision and evidence version. If another tab
changes the review or query evidence changes, saving returns **409**. Refresh
evidence, inspect it, then save again; the frontend preserves the draft note during
this refresh. No review write changes query logs, feedback, retrieval settings,
caches, documents, or provider behavior.

Evidence follows existing query-log retention. Groups without retained matching
queries in the selected window are hidden, including resolved groups. The small
review record persists until its project is deleted; it contains no copied query
or answer text. Deleting a project cascades its reviews. Historical answers and
source passages are not reconstructed from caches.

## Dashboard API

All endpoints require the signed-in owner's dashboard token with existing MFA,
suspension, and rate-limit enforcement. Project API keys cannot manage this inbox.
Every read and write is scoped through the owning project.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/account/knowledge-gaps` | Filtered report; `days`, `project_id`, `status=open\|resolved\|all`, `search`, `recurring`, `offset`, `limit`. |
| GET | `/api/account/knowledge-gaps/{project_id}/{key}` | Group and paginated evidence; `days`, `offset`, `limit`. |
| PUT | `/api/account/knowledge-gaps/{project_id}/{key}` | Save `{status, note, revision, evidence_version, verification_run_id}` for the selected `days`; returns refreshed detail. |
| GET | `/api/projects/{project_id}/gaps/{key}/verification` | Latest verification runs plus the attached resolution evidence. |
| POST | `/api/projects/{project_id}/gaps/{key}/verification` | Start selected query checks with an idempotent run ID and current evidence version; uses provider credits. |

The key is a 64-character lowercase hex SHA-256 digest. Limits are 1–100 per
page; offsets are 0–5,000. Invalid filters return 422, inaccessible projects or
absent evidence return 404, and stale reviews/evidence return 409. GETs never
write and no provider calls are made by report or review endpoints. Starting a
verification creates a background evaluation and uses provider credits.

## Deployment

Apply `supabase/migrations/0048_knowledge_gaps.sql` before deploying this backend
and frontend. It adds only `knowledge_gap_reviews`, with a composite primary key,
project cascade, validation constraints, and RLS. Direct authenticated Supabase
clients can read only their own projects' reviews; writes go through the API's
ownership and concurrency checks.

Verification also requires `supabase/migrations/0050_review_workflows.sql`, which
adds the run linkage and workflow metadata. This clarification of review states
uses those existing columns and does not require another migration.
