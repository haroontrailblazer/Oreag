import hashlib
import hmac
import json
import unittest
import httpx
from oreag import DISCOVERY_URL, FALLBACK_BASE_URL, Oreag, OreagError, verify_webhook

BASE = "https://example.test"


class SDKTests(unittest.TestCase):
    def test_idempotency_headers(self):
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(200,json={"answer":"ok"})
        with Oreag("test","project",base_url=BASE,transport=httpx.MockTransport(handler)) as c:
            c.query("Hi",top_k=3,idempotency_key="logical-query")
            self.assertEqual(calls[-1].headers["Idempotency-Key"],"logical-query")
            self.assertNotIn("idempotency_key",json.loads(calls[-1].content))
            c.upload_files([("fixture.txt",b"fixture")],idempotency_key="logical-upload")
            self.assertEqual(calls[-1].headers["Idempotency-Key"],"logical-upload")
            c.start_evaluation("run",{"cases":[],"variants":[]},idempotency_key="logical-eval")
            self.assertEqual(calls[-1].headers["Idempotency-Key"],"logical-eval")
    def test_query_feedback_upload(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"answer": "ok"})
        with Oreag("test", "project", base_url=BASE, transport=httpx.MockTransport(handler)) as client:
            self.assertEqual(client.query("Question?", top_k=3, conversation_id="thread")["answer"], "ok")
            self.assertEqual(json.loads(calls[0].content)["top_k"], 3)
            client.feedback("9007199254740993", "not_helpful", "Missing policy")
            self.assertIn("9007199254740993/feedback", str(calls[-1].url))
            client.upload_files([("policy.txt", b"Policy")])
            self.assertIn(b'name="uploads"', calls[-1].content)

    def test_stream_and_incomplete(self):
        data = 'data: {"type":"token","text":"தமிழ்"}\r\n\r\ndata: {"type":"done","response":{"answer":"ok"}}'
        with Oreag("test", "project", base_url=BASE, transport=httpx.MockTransport(lambda r: httpx.Response(200, text=data))) as c:
            events = list(c.stream_query("Hi"))
            self.assertEqual(events[0]["text"], "தமிழ்")
            self.assertEqual(events[-1]["type"], "done")
        for data in ['data: {"type":"token","text":"partial"}\n\n', 'data: {"type":"error","detail":"Busy"}\n\n']:
            with Oreag("test", "project", base_url=BASE, transport=httpx.MockTransport(lambda r: httpx.Response(200, text=data))) as c:
                with self.assertRaises(OreagError): list(c.stream_query("Hi"))

    def test_errors_never_retry(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(429, json={"detail": "Rate limited"}, headers={"Retry-After": "20"})
        with Oreag("test", "project", base_url=BASE, transport=httpx.MockTransport(handler)) as c:
            with self.assertRaises(OreagError) as result: c.query("Hi")
            self.assertEqual(result.exception.retry_after, "20")
            self.assertEqual(len(calls), 1)

    def test_webhook_signature(self):
        body = b'{"id":"evt"}'
        headers = {"Oreag-Timestamp": "1000", "Oreag-Signature": "v1=" + hmac.new(b"secret", b"1000." + body, hashlib.sha256).hexdigest()}
        self.assertEqual(verify_webhook(body, headers, "secret", now=1000)["id"], "evt")
        with self.assertRaises(ValueError): verify_webhook(body + b" ", headers, "secret", now=1000)
        with self.assertRaises(ValueError): verify_webhook(body, headers, "secret", now=1400)


class DiscoveryTests(unittest.TestCase):
    """Without base_url the client follows the hosted API between its two servers."""

    def client(self, serving, calls, *, discovery_status=200):
        def handler(request):
            calls.append(request)
            if str(request.url) == DISCOVERY_URL:
                return httpx.Response(discovery_status, json={"apiBase": serving[0]})
            if request.url.host == "suspended.test":
                return httpx.Response(503, text="<html>suspended</html>", headers={"x-render-routing": "suspend-by-user"})
            return httpx.Response(200, json={"answer": "ok"})
        return Oreag("test", "project", transport=httpx.MockTransport(handler))

    def test_calls_the_server_discovery_names_without_sending_the_key_there(self):
        calls = []
        with self.client(["https://standby.test"], calls) as c:
            c.query("Hi")
        self.assertEqual(str(calls[0].url), DISCOVERY_URL)
        self.assertNotIn("authorization", calls[0].headers)
        self.assertEqual(calls[1].url.host, "standby.test")
        self.assertEqual(calls[1].headers["authorization"], "Bearer test")

    def test_answer_is_reused_between_calls(self):
        calls = []
        with self.client(["https://standby.test"], calls) as c:
            c.query("Hi")
            c.query("Again")
        self.assertEqual(sum(str(r.url) == DISCOVERY_URL for r in calls), 1)

    def test_suspended_server_is_reported_and_forgotten_without_retrying(self):
        calls, serving = [], ["https://suspended.test"]
        with self.client(serving, calls) as c:
            with self.assertRaises(OreagError) as result:
                c.query("Hi")
            self.assertEqual(result.exception.status, 503)
            self.assertEqual(sum(r.url.host == "suspended.test" for r in calls), 1)
            serving[0] = "https://standby.test"
            self.assertEqual(c.query("Hi")["answer"], "ok")
        self.assertEqual(calls[-1].url.host, "standby.test")

    def test_unreachable_discovery_falls_back_to_the_primary(self):
        calls = []
        with self.client(["https://standby.test"], calls, discovery_status=502) as c:
            c.query("Hi")
        self.assertEqual(str(calls[-1].url).split("/v1/")[0], FALLBACK_BASE_URL)

    def test_explicit_base_url_never_asks(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"answer": "ok"})
        with Oreag("test", "project", base_url=BASE, transport=httpx.MockTransport(handler)) as c:
            c.query("Hi")
        self.assertEqual([r.url.host for r in calls], ["example.test"])


if __name__ == "__main__": unittest.main()
