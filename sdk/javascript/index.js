export class OreagError extends Error {
  constructor(message, status = 0, detail = null, retryAfter = null) {
    super(message); this.name = "OreagError"; this.status = status; this.detail = detail; this.retryAfter = retryAfter;
  }
}

export class OreagClient {
  constructor({ apiKey, projectId, baseUrl = "https://oreag.onrender.com", fetch: transport = globalThis.fetch }) {
    if (!apiKey || !projectId) throw new TypeError("apiKey and projectId are required");
    this.base = `${baseUrl.replace(/\/$/, "")}/v1/projects/${encodeURIComponent(projectId)}`;
    this.apiKey = apiKey; this.fetch = transport;
  }
  async request(path, { method = "GET", body, signal, stream = false, idempotencyKey } = {}) {
    let response;
    try {
      response = await this.fetch(this.base + path, { method, signal, redirect: "error",
        headers: { ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}), Authorization: `Bearer ${this.apiKey}`, ...(body !== undefined && !(body instanceof FormData) ? { "Content-Type": "application/json" } : {}) },
        ...(body !== undefined ? { body: body instanceof FormData ? body : JSON.stringify(body) } : {}) });
    } catch (e) {
      if (signal?.aborted) throw e;
      throw new OreagError("Could not reach Oreag. The request may have been accepted; it was not retried.");
    }
    if (!response.ok) {
      let detail = null;
      try { detail = (await response.json()).detail; } catch { /* Non-JSON gateway error. */ }
      throw new OreagError(typeof detail === "string" ? detail : `Oreag returned HTTP ${response.status}`, response.status, detail, response.headers.get("retry-after"));
    }
    if (stream) return response;
    return response.status === 204 ? undefined : response.json();
  }
  query(question, options = {}) { const { signal, idempotencyKey, ...body } = options; return this.request("/query", { method: "POST", body: { ...body, question }, signal, idempotencyKey }); }
  async *streamQuery(question, options = {}) {
    const { signal, ...body } = options;
    const response = await this.request("/query/stream", { method: "POST", body: { ...body, question }, signal, stream: true });
    if (!response.body) throw new OreagError("The response has no stream.");
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = "", lines = [], finished = false;
    function parse() {
      const data = lines.filter(l => l.startsWith("data:")).map(l => l.slice(5).replace(/^ /, "")).join("\n"); lines = [];
      if (!data) return null;
      let event;
      try { event = JSON.parse(data); } catch { throw new OreagError("Invalid stream event."); }
      if (!event || typeof event !== "object" || typeof event.type !== "string") throw new OreagError("Invalid stream event.");
      if (event.type === "error") throw new OreagError(event.detail || "Streaming query failed.", 0, event);
      return event;
    }
    try {
      while (!finished) {
        const chunk = await reader.read();
        buffer += decoder.decode(chunk.value, { stream: !chunk.done });
        if (chunk.done) buffer += "\n\n";
        let newline;
        while ((newline = buffer.indexOf("\n")) !== -1) {
          const line = buffer.slice(0, newline).replace(/\r$/, ""); buffer = buffer.slice(newline + 1);
          if (line) lines.push(line);
          else {
            const event = parse();
            if (event) { finished = event.type === "done"; yield event; if (finished) break; }
          }
        }
        if (buffer.length > 8_000_000 || lines.join("").length > 8_000_000) throw new OreagError("Stream event is too large.");
        if (chunk.done && !finished) throw new OreagError("Stream ended before the final answer.");
      }
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  }
  uploadFiles(files, { signal, idempotencyKey } = {}) {
    const form = new FormData();
    for (const { data, name } of files) form.append("uploads", data, name);
    return this.request("/files", { method: "POST", body: form, signal, idempotencyKey });
  }
  feedback(queryId, rating, note = "") { return this.request(`/queries/${encodeURIComponent(queryId)}/feedback`, { method: "PUT", body: { rating, note } }); }
  clearFeedback(queryId) { return this.request(`/queries/${encodeURIComponent(queryId)}/feedback`, { method: "DELETE" }); }
  getQuery(queryId) { return this.request(`/queries/${encodeURIComponent(queryId)}`); }
  health() { return this.request("/health"); }
  getTestSet() { return this.request("/evaluations/suite"); }
  addToTestSet(queryId, expected, revision, options = {}) { return this.request("/evaluations/cases/from-query", { method: "POST", body: { ...options, query_id: queryId, expected, revision } }); }
  startEvaluation(id, suite, referenceRunId = null, { idempotencyKey } = {}) { return this.request("/evaluations/runs", { method: "POST", body: { id, suite, background: true, reference_run_id: referenceRunId }, idempotencyKey }); }
  getEvaluation(id) { return this.request(`/evaluations/runs/${encodeURIComponent(id)}`); }
  cancelEvaluation(id) { return this.request(`/evaluations/runs/${encodeURIComponent(id)}/cancel`, { method: "POST" }); }
}
