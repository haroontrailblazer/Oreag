# Oreag JavaScript SDK

Node.js 18+ with native fetch. Install with `npm install @haroontrailblazer/oreag-sdk`.
For development from a checkout, use `npm install ./sdk/javascript`.

```js
import { OreagClient, OreagError } from '@haroontrailblazer/oreag-sdk';
const oreag = new OreagClient({ apiKey: process.env.OREAG_API_KEY, projectId: process.env.OREAG_PROJECT_ID });
const answer = await oreag.query('What is the policy?', { top_k: 5, conversation_id: 'session-1' });
for await (const event of oreag.streamQuery('Explain the policy')) {
  if (event.type === 'token') process.stdout.write(event.text);
}
// Submit a rating only after collecting it from the user:
if (answer.query_id !== null) {
  await oreag.feedback(answer.query_id, 'not_helpful', 'Missing the new policy');
  const saved = await oreag.getTestSet();
  await oreag.addToTestSet(answer.query_id, 'Return within 30 days.', saved.revision);
}
```

`uploadFiles([{data: Blob, name: 'policy.txt'}])` requires an upload-enabled key. Wait for `file.indexed` before querying new content. `getQuery(id)` includes the timing timeline; `health()` reads knowledge health. `startEvaluation(crypto.randomUUID(), suite)` queues a background run; poll `getEvaluation(id)` or subscribe to completion webhooks. Existing question, answer, source, conversation, and cache fields are preserved. Pass an AbortSignal to query/stream/upload; breaking a stream closes the reader.

Errors have `status`, `detail`, and `retryAfter`. No requests are retried automatically, including ambiguous connection failures, preventing duplicate uploads or provider charges. Respect Retry-After and retry only when your application knows the operation is safe. Never put API keys in browser bundles.

```js
import { verifyWebhook } from '@haroontrailblazer/oreag-sdk/webhooks';
// rawBody is the exact Uint8Array received by your HTTP server, before JSON parsing.
const event = verifyWebhook(rawBody, request.headers, process.env.OREAG_WEBHOOK_SECRET);
// Persist event.id with a UNIQUE constraint and queue your work atomically.
// Return 2xx after persistence; repeated event IDs are successful no-ops.
```

Signature verification allows five minutes of clock skew. Preserve the raw body; never reserialize JSON before verification. Events can repeat and arrive out of order. `examples.mjs` is runnable with environment variables. Run `npm test` for transport and signature tests.

## Safe retries (0.2.0)

Pass `{ idempotencyKey: "one-logical-request" }` to `query` or `uploadFiles`, or as the fourth argument to `startEvaluation(id, suite, referenceId, options)`. Reuse the same key and content after a lost response. The server retains encrypted completed responses for 24 hours, scoped to the API key and operation. Different content returns 409; pending or uncertain work also returns 409 and is never executed again with that key within the retention window. Inspect the resource before creating a new key for an uncertain operation. Streaming does not support this header. These clients never retry automatically.

See `CHANGELOG.md` for release changes. Versioned packages are built and tested by the repository SDK release workflow.

## License

The SDK retains the Oreag proprietary, viewing-only license in `LICENSE`. Publication or download does not grant application-use rights; obtain the owner's written permission for use beyond that license.
