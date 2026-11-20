# Changelog

## 0.3.0

- Without an explicit base URL the client asks https://oreag.vercel.app/api/active-backend which server is serving and follows the hosted API between its two servers on its own. The API key is never sent to that endpoint.
- A request that reaches a suspended server fails with status 503 and a clear message; Render never passed it to the API, so it is safe to send again. It is still not retried automatically.
- Passing a base URL keeps the old fixed behaviour.

## 0.2.0

- Optional idempotency keys for buffered queries, uploads and evaluation creation.
- Typed uploads, streaming answers, feedback, query timelines, Health and background evaluations.
- Signed webhook verification and runnable examples.
- Existing question, answer, source, conversation and cache fields remain compatible.
- Interrupted streams and uncertain requests are never automatically retried.

## 0.1.0

Initial source distribution.
