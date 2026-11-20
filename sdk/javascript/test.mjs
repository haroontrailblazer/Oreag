import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { DISCOVERY_URL, FALLBACK_BASE_URL, OreagClient, OreagError } from "./index.js";
import { verifyWebhook } from "./webhooks.js";
const options = { apiKey: "test", projectId: "project", baseUrl: "https://example.test" };
test("idempotency keys are headers and never leak into query bodies", async () => {
  const calls = [];
  const client = new OreagClient({ ...options, fetch: async (url, init) => { calls.push(init); return Response.json({answer:"ok"}); } });
  await client.query("Hi", {idempotencyKey:"logical-query",top_k:3});
  assert.equal(calls[0].headers["Idempotency-Key"],"logical-query");
  assert.deepEqual(JSON.parse(calls[0].body),{question:"Hi",top_k:3});
  await client.uploadFiles([{name:"fixture.txt",data:new Blob(["fixture"])}],{idempotencyKey:"logical-upload"});
  assert.equal(calls[1].headers["Idempotency-Key"],"logical-upload");
  await client.startEvaluation("run",{cases:[],variants:[]},null,{idempotencyKey:"logical-eval"});
  assert.equal(calls[2].headers["Idempotency-Key"],"logical-eval");
});
test("query, feedback and uploads preserve the public contract", async () => {
  const calls = [];
  const client = new OreagClient({ ...options, fetch: async (url, init) => { calls.push({ url, ...init }); return Response.json({ answer: "ok" }); } });
  assert.equal((await client.query("Question?", { top_k: 3, conversation_id: "thread" })).answer, "ok");
  assert.deepEqual(JSON.parse(calls[0].body), { question: "Question?", top_k: 3, conversation_id: "thread" });
  assert.equal(calls[0].headers.Authorization, "Bearer test");
  await client.feedback("9007199254740993", "not_helpful", "Missing policy");
  assert.match(calls[1].url, /9007199254740993\/feedback$/);
  await client.uploadFiles([{ name: "policy.txt", data: new Blob(["Policy"]) }]);
  assert.equal(calls[2].body.get("uploads").name, "policy.txt");
});
test("split UTF8 and CRLF streams complete and close", async () => {
  const bytes = new TextEncoder().encode('data: {"type":"token","text":"தமிழ்"}\r\n\r\ndata: {"type":"done","response":{"answer":"ok"}}');
  let closed = false;
  const stream = new ReadableStream({ start(c) { for (const b of bytes) c.enqueue(Uint8Array.of(b)); c.close(); }, cancel() { closed = true; } });
  const client = new OreagClient({ ...options, fetch: async () => new Response(stream) });
  const events = [];
  for await (const e of client.streamQuery("Hi")) events.push(e);
  assert.equal(events[0].text, "தமிழ்"); assert.equal(events[1].type, "done");
});
test("partial stream, server errors and HTTP failures are typed and not retried", async () => {
  for (const value of ['data: {"type":"token","text":"partial"}\n\n', 'data: {"type":"error","detail":"Provider busy"}\n\n']) {
    const c = new OreagClient({ ...options, fetch: async () => new Response(value) });
    await assert.rejects(async () => { for await (const e of c.streamQuery("Hi")) {} }, OreagError);
  }
  let calls = 0;
  const c = new OreagClient({ ...options, fetch: async () => { calls++; return Response.json({ detail: "Rate limited" }, { status: 429, headers: { "Retry-After": "20" } }); } });
  await assert.rejects(c.query("Hi"), e => e.status === 429 && e.retryAfter === "20");
  assert.equal(calls, 1);
});
test("webhook verification rejects altered body and replay", () => {
  const body = '{"id":"evt"}', timestamp = "1000";
  const headers = { "oreag-timestamp": timestamp, "oreag-signature": "v1=" + createHmac("sha256", "secret").update(timestamp + "." + body).digest("hex") };
  assert.equal(verifyWebhook(body, headers, "secret", { now: 1000 }).id, "evt");
  assert.throws(() => verifyWebhook(body + " ", headers, "secret", { now: 1000 }));
  assert.throws(() => verifyWebhook(body, headers, "secret", { now: 1400 }));
});

function discoveryClient(serving, calls, discoveryStatus = 200) {
  return new OreagClient({ apiKey: "test", projectId: "project", fetch: async (url, init = {}) => {
    calls.push({ url: String(url), ...init });
    if (String(url) === DISCOVERY_URL) return Response.json({ apiBase: serving[0] }, { status: discoveryStatus });
    if (new URL(url).host === "suspended.test") return new Response("<html>suspended</html>", { status: 503, headers: { "x-render-routing": "suspend-by-user" } });
    return Response.json({ answer: "ok" });
  } });
}
test("without baseUrl the client calls the server discovery names and keeps the key to itself", async () => {
  const calls = [];
  const c = discoveryClient(["https://standby.test"], calls);
  await c.query("Hi"); await c.query("Again");
  assert.equal(calls[0].url, DISCOVERY_URL);
  assert.equal(calls[0].headers, undefined);
  assert.equal(new URL(calls[1].url).host, "standby.test");
  assert.equal(calls[1].headers.Authorization, "Bearer test");
  assert.equal(calls.filter(call => call.url === DISCOVERY_URL).length, 1);
});
test("a suspended server is reported, forgotten and never retried", async () => {
  const calls = [], serving = ["https://suspended.test"];
  const c = discoveryClient(serving, calls);
  await assert.rejects(c.query("Hi"), e => e instanceof OreagError && e.status === 503);
  assert.equal(calls.filter(call => new URL(call.url).host === "suspended.test").length, 1);
  serving[0] = "https://standby.test";
  assert.equal((await c.query("Hi")).answer, "ok");
  assert.equal(new URL(calls.at(-1).url).host, "standby.test");
});
test("an unreachable discovery endpoint falls back to the primary", async () => {
  const calls = [];
  await discoveryClient(["https://standby.test"], calls, 502).query("Hi");
  assert.ok(calls.at(-1).url.startsWith(FALLBACK_BASE_URL + "/v1/"));
});
