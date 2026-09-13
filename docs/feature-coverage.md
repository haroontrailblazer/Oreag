# Dashboard feature coverage

The source code is the authority for behavior. This inventory connects the
implemented dashboard features to their in-app documentation and LikeC4 elements.
The interactive diagram is served at `/architecture`; its editable source is
[`frontend/public/architecture.c4`](../frontend/public/architecture.c4).

| Feature | Implementation | In-app docs section | Diagram element |
|---|---|---|---|
| Spending-change insights | `frontend/src/lib/usage-insights.ts` | Usage Analytics → Spending changes and estimates | `spendingInsights` |
| Budget forecast | `frontend/src/lib/budget-forecast.ts` | Usage Analytics → Budget forecast | `budgetForecast` |
| Budgets and alerts | `backend/app/services/budgets.py` | Usage Analytics → Budgets and alerts | `budgets` |
| Query history | `backend/app/services/query_history.py` | Queries | `queryHistory` |
| Query timeline | `backend/app/services/query_timeline.py` | Queries → Query debugging timeline | `queryTimeline` |
| Cache inspector | `backend/app/services/cache_insights.py` | Queries → Cache inspector | `cacheInsights` |
| Failed request explorer | `backend/app/services/request_failures.py` | Queries → Failed request explorer | `requestFailures` |
| Saved views | `backend/app/routers/saved_views.py` | Queries → Saved views | `savedViews` |
| Project readiness | `backend/app/services/knowledge_health.py` | Health → Readiness and diagnostics | `knowledgeHealth` |
| Quality trends | `backend/app/services/quality_trends.py` | Health → Quality trends | `qualityTrends` |
| Document impact and freshness | `backend/app/services/document_insights.py` | Health → Document impact and freshness | `documentInsights` |
| Gaps | `backend/app/services/knowledge_gaps.py` | Knowledge gaps | `knowledgeGaps` |
| Gap verification | `backend/app/routers/gap_verification.py` | Knowledge gaps → Verify fix | `gapVerification` |
| Evaluator | `backend/app/services/evaluations.py` | Querying → Evaluation playground | `evaluations` |
| Automatic checks after changes | `backend/app/services/quality.py` | Creating & Managing Projects → Automatic checks after changes | `quality` |
| Source conflict review | `backend/app/services/source_conflicts.py` | Files & Indexing Management → Source conflict review | `sourceConflicts` |
| Page preloading | `frontend/src/components/dashboard-prefetch.tsx` | Dashboard & Projects Overview → Page preloading | `navigationPrefetch` |

The model splits these features across three focused views: Navigation and
spending, Queries and Health, and Gaps and verification. Core ingestion, retrieval,
memory, authentication, provider resolution and deployment retain their existing
views and documentation sections.

## Important distinctions

- Spending effects describe recorded arithmetic changes. Forecasts are estimates,
  not invoices or spending caps; missing costs remain unknown.
- Gaps excludes recognized casual speech from weak-match signals. Negative feedback
  still warrants review, and a low match alone does not prove an incorrect answer.
- Close review records a decision. Resolve with verification attaches current,
  complete passing checks. Improvement requires a comparable prior result.
- Quality trends and document attribution are measurements, not accuracy scores.
  Freshness requires a recorded content review, not just an upload or indexing time.
- Saved views save filters. Cache inspector describes observed decisions. Neither
  reconstructs historical answers. Reviewing a conflict does not edit its sources.

## Schema requirements

Apply migrations in order through `0050_review_workflows.sql`. Relevant additions
are `0043` answer feedback, `0044` evaluator storage, `0045` budgets, `0046` quality
schedules/webhooks/timelines, `0047` operational reliability, `0048` gap reviews,
`0049` document attribution/reviews, and `0050` review workflows. The spending
insights, forecasts and navigation changes require no separate migration.

## Verification

`python scripts/check_docs_sync.py` checks extracted routes, MCP tools, services,
configuration facts, feature documentation, connected diagram elements, sidebar
navigation and local documentation images. `backend/tests/test_docs_sync.py`
also tests that the harness detects deliberate drift.

Feature regression tests cover budgets, query/cache safety, Gaps and verification,
Saved views, conflict decisions, quality trends, document reviews, failed requests,
evaluations, and automatic checks. Frontend scripts cover spending arithmetic,
forecast boundaries and missing costs, evaluation comparisons, and preloading.
`npm run build -- --webpack` rebuilds the interactive architecture viewer and app.

These checks validate the repository and local rendered output. They do not
certify a live database migration state, external provider availability, or
production throughput.
