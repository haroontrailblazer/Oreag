# Answer feedback

Project owners can mark completed Playground answers helpful or not helpful,
add an optional note of up to 1,000 characters, change the rating, or remove it.
Feedback is stored on the query log. In **Queries**, use **Answer feedback** to
filter helpful, not helpful, or unrated queries; open a query to review or edit
its feedback. There is no additional sidebar page.

Each invocation receives its own string `query_id`, including exact and semantic
cache hits. Ratings do not change retrieval, prompts, cached answers, or model
behavior. Answers and sources are not newly retained. If logging fails, the
answer is still returned with a null query ID and feedback controls are omitted.

## Deployment

Apply `supabase/migrations/0043_answer_feedback.sql` before deploying the updated
backend. This additive migration leaves existing queries unrated and uses the
existing project-owner RLS policy on `query_logs`. Removing a project also removes
its query logs and feedback through the existing cascade.

## Dashboard API

Authenticated owner access is required for both endpoints:

- `PUT /api/account/queries/{query_id}/feedback` with
  `{"rating":"helpful","note":"Optional explanation"}`.
  `rating` is `helpful` or `not_helpful`; saving replaces the prior rating
  and note for that query. The response is the updated query record.
- `DELETE /api/account/queries/{query_id}/feedback` removes the rating and note,
  returning 204. Repeating removal is safe.

The Queries list accepts `feedback=all|helpful|not_helpful|unrated`, combined with
the existing project, time, cache, search, latency, and cursor filters. List
responses include the rating and update timestamp; full notes are detail-only.

## Public API

Call these endpoints from your server with
`Authorization: Bearer YOUR_OREAG_API_KEY`. No owner session or upload permission
is required. The key must be active and belong to the project in the URL.

- `PUT /v1/projects/{project_id}/queries/{query_id}/feedback` saves or replaces
  feedback. Body: `{"rating":"not_helpful","note":"The policy was missing."}`.
  `rating` must be `helpful` or `not_helpful`. `note` is optional, trimmed, and
  limited to 1,000 characters; omitted or blank notes clear the prior note.
- `DELETE /v1/projects/{project_id}/queries/{query_id}/feedback` removes feedback
  and returns 204 with no body. Repeating removal on an existing query is safe.

A successful PUT returns 200:

```json
{
  "query_id": "12345",
  "rating": "not_helpful",
  "note": "The policy was missing.",
  "updated_at": "2026-09-10T06:00:00Z"
}
```

Use `query_id` from the `/query` response, or `response.query_id` in the
`/query/stream` terminal `done` event. Keep it as a string to avoid JavaScript
bigint precision loss. If it is null, logging failed and that answer cannot
receive feedback. Each cache-hit invocation has its own ID.

Any active key belonging to the project can update feedback for any of its
queries, including queries made with another key or in Playground. There is one
shared rating per query, not one vote per end user: the latest save replaces it.
Project owners see and manage public feedback in **Queries**. Your server should
associate each query ID with the appropriate end user before accepting their
feedback; keep the project API key on your server.

Missing, invalid, revoked, or wrong-project keys return 401. Suspended projects
or accounts return 403. Missing or out-of-project query IDs return 404. Invalid
ratings, notes, or unknown body fields return 422. Both endpoints share the
standard request budgets (120/min per key, 300/min per project by default);
429 responses include `Retry-After`. Feedback does not call an AI provider or
create a new query. No additional migration beyond 0043 is required.

## Monitoring production API traffic

The public API is the application integration surface; Playground tests the same
query engine and project configuration. Both buffered and streaming API answers
are recorded in the same query log that powers **Queries** and **Health**.
Queries shows all recorded invocations, including cache hits and public feedback.
Health includes documents uploaded through either surface and shows each
project's total queries, cache hits, and current helpful / not helpful ratings
for queries made in the last 30 days. Its retrieval-similarity average still uses
only measured, uncached queries; missing measurements stay null.

Queries refreshes its first page every 30 seconds while visible and online;
older pages keep their pagination position. Health refreshes on the same
interval, so activity from an external application appears without a browser
reload. Both also refresh on window focus and support manual refresh. Failed or
interrupted requests that do not produce a query log are not listed as completed
queries. These owner reports require a dashboard session; a project API key does
not grant access to account-wide monitoring data.


## Project-scoped monitoring API

Active project keys can also call `GET /v1/projects/{project_id}/queries`,
`GET /v1/projects/{project_id}/queries/{query_id}`, and
`GET /v1/projects/{project_id}/health`. These use the same read services as the
owner dashboard, scoped to exactly the key's project. History includes queries
from other keys and Playground within that project; full questions and feedback
notes are available in detail. Protect these server-side credentials accordingly.
All three endpoints use the standard rate limit and suspension checks.
Health returns the report envelope with exactly one project; account-wide
reports remain owner-session only. No new database migration is required.
