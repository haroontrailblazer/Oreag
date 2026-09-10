# Oreag Python SDK

Python 3.10+. Install a published release with `pip install oreag-sdk`.
For a source checkout, run `pip install ./sdk/python` from the repository root.

```python
import os
from oreag import Oreag, OreagError
with Oreag(os.environ['OREAG_API_KEY'], os.environ['OREAG_PROJECT_ID']) as oreag:
    answer = oreag.query('What is the policy?', top_k=5, conversation_id='session-1')
    for event in oreag.stream_query('Explain the policy'):
        if event['type'] == 'token':
            print(event['text'], end='', flush=True)
    # Submit a rating only after collecting it from the user:
    if answer['query_id'] is not None:
        oreag.feedback(answer['query_id'], 'not_helpful', 'Missing the new policy')
        saved = oreag.get_test_set()
        oreag.add_to_test_set(answer['query_id'], 'Return within 30 days.', saved['revision'])
```

Use `upload_files([('policy.txt', binary_file)])` with an upload-enabled key. Wait for the `file.indexed` event before querying new content. `get_query(id)` includes query timings; `health()` reads knowledge health. `start_evaluation(str(uuid.uuid4()), suite)` queues a background run; poll `get_evaluation(id)` or subscribe to completion events. Request/answer/source/conversation fields match the public API.

`OreagError` exposes `status`, `detail`, and `retry_after`. Requests are never automatically retried; an interrupted request may already have incurred cost. Respect Retry-After and retry only when safe. Close partially consumed streaming generators explicitly (`stream.close()` or `contextlib.closing`) to release the connection. Keep API keys on your server. `example.py` runs with OREAG_API_KEY and OREAG_PROJECT_ID environment variables.

```python
from oreag import verify_webhook
event = verify_webhook(raw_request_bytes, request_headers, signing_secret)
# Persist event['id'] with a UNIQUE constraint and queue work atomically.
# Return 2xx after persistence; duplicate events should be successful no-ops.
```

Verify the exact raw bytes before parsing JSON. Verification allows five minutes of clock skew. Events can repeat and arrive out of order. Run `python -m unittest test_sdk.py` from this directory.

## Safe retries (0.2.0)

Pass `idempotency_key="one-logical-request"` to `query`, `upload_files`, or `start_evaluation`. Reuse the same key and content after a lost response. The server retains encrypted completed responses for 24 hours, scoped to the API key and operation. Different content returns 409; pending or uncertain work also returns 409 and is never executed again with that key within the retention window. Inspect the resource before creating a new key for an uncertain operation. Streaming does not support this header. These clients never retry automatically.

See `CHANGELOG.md` for release changes. Versioned packages are built and checked by the repository SDK release workflow.

## License

The SDK retains the Oreag proprietary, viewing-only license in `LICENSE`. Publication or download does not grant application-use rights; obtain the owner's written permission for use beyond that license.
