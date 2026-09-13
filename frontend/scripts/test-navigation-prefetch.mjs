import assert from "node:assert/strict"
import { test } from "node:test"
import { createNavigationPrefetchQueue, dashboardBackgroundTargets, dashboardPrefetchTarget, DASHBOARD_ROUTES } from "../src/lib/navigation-prefetch.ts"

const tick = () => new Promise(resolve => setImmediate(resolve))
function harness(run = async () => true) {
  const tasks = new Map()
  const calls = []
  let id = 0
  let time = 0
  let paused = false
  const queue = createNavigationPrefetchQueue({
    run: async href => { calls.push(href); return run(href) },
    schedule: callback => { const key = ++id; tasks.set(key, callback); return () => tasks.delete(key) },
    now: () => time,
    paused: () => paused,
  })
  return {
    queue, calls, tasks,
    setTime: value => { time = value },
    setPaused: value => { paused = value },
    async step() {
      const next = tasks.entries().next().value
      if (next) { tasks.delete(next[0]); next[1]() }
      await tick()
    },
  }
}

test("only prefetches known dashboard/project pages and preserves deep links", () => {
  for (const href of DASHBOARD_ROUTES) assert.equal(dashboardPrefetchTarget(href, "https://oreag.test", []), href)
  assert.equal(dashboardPrefetchTarget("/projects/abc?tab=api#keys", "https://oreag.test", ["abc"]), "/projects/abc?tab=api")
  for (const href of ["/api/account", "/auth/callback", "/login", "/projects/unknown", "https://outside.test/settings/usage", "javascript:alert(1)", "http://["]) {
    assert.equal(dashboardPrefetchTarget(href, "https://oreag.test", ["abc"]), null)
  }
})

test("deduplicates queued, in-flight and fresh completed work", async () => {
  let finish
  const h = harness(() => new Promise(resolve => { finish = resolve }))
  h.queue.enqueue("/a"); h.queue.enqueue("/a")
  assert.equal(h.tasks.size, 1)
  await h.step()
  h.queue.enqueue("/a", true)
  assert.deepEqual(h.calls, ["/a"])
  finish(true); await tick()
  h.queue.enqueue("/a")
  assert.equal(h.tasks.size, 0)
})

test("intent starts immediately beside a slow background request, with bounded concurrency", async () => {
  const finish = new Map()
  const h = harness(href => new Promise(resolve => { finish.set(href, resolve) }))
  h.queue.enqueue("/a"); h.queue.enqueue("/b"); h.queue.enqueue("/c")
  await h.step()
  assert.equal(h.tasks.size, 0)
  h.queue.enqueue("/c", true)
  await tick()
  assert.deepEqual(h.calls, ["/a", "/c"])
  h.queue.enqueue("/b", true); await tick()
  assert.deepEqual(h.calls, ["/a", "/c"])
  finish.get("/c")(true); await tick()
  assert.deepEqual(h.calls, ["/a", "/c", "/b"])
  finish.get("/a")(true); finish.get("/b")(true); await tick()
})

test("intent bypasses the idle timer even before any background job starts", async () => {
  const h = harness()
  h.queue.enqueue("/background")
  h.queue.enqueue("/hover", true)
  await tick()
  assert.deepEqual(h.calls, ["/hover"])
  await h.step()
  assert.deepEqual(h.calls, ["/hover", "/background"])
})

test("background warming includes new pages but bounds project requests", () => {
  const projects = Array.from({ length: 100 }, (_, i) => `/projects/${i}`)
  const targets = dashboardBackgroundTargets(projects, "/projects/0")
  assert(targets.includes("/knowledge-gaps"))
  assert(targets.includes("/query-explorer?view=failures"))
  assert.deepEqual(targets.filter(href => projects.includes(href)), ["/projects/1", "/projects/2", "/projects/3"])
  assert.equal(dashboardPrefetchTarget("/projects/99", "https://oreag.test", ["99"]), "/projects/99")
})

test("hidden/offline work resumes without losing queued pages", async () => {
  const h = harness()
  h.setPaused(true); h.queue.enqueue("/a")
  assert.equal(h.tasks.size, 0)
  h.setPaused(false); h.queue.resume(); await h.step()
  assert.deepEqual(h.calls, ["/a"])
})

test("failed or unauthenticated speculation can be retried", async () => {
  let attempt = 0
  const h = harness(async () => { attempt++; if (attempt === 1) throw new Error("offline"); return attempt > 2 })
  for (let count = 0; count < 3; count++) { h.queue.enqueue("/a"); await h.step() }
  assert.equal(h.calls.length, 3)
  h.queue.enqueue("/a")
  assert.equal(h.tasks.size, 0)
})

test("expired entries refresh on new intent without a background polling loop", async () => {
  const h = harness()
  h.queue.enqueue("/a"); await h.step()
  assert.equal(h.tasks.size, 0)
  h.setTime(30_001); h.queue.enqueue("/a", true); await h.step()
  assert.equal(h.calls.length, 2)
})

test("Next invalidation permits a new prefetch without waiting for the TTL", async () => {
  const h = harness()
  h.queue.enqueue("/a"); await h.step()
  h.queue.invalidate("/a")
  h.queue.enqueue("/a", true); await tick()
  assert.deepEqual(h.calls, ["/a", "/a"])
})

test("unmount/sign-out cancels pending work, including after an active job finishes", async () => {
  let finish
  const h = harness(() => new Promise(resolve => { finish = resolve }))
  h.queue.enqueue("/a"); h.queue.enqueue("/b"); await h.step()
  h.queue.dispose(); finish(true); await tick()
  assert.equal(h.tasks.size, 0)
  h.queue.enqueue("/c"); await h.step()
  assert.deepEqual(h.calls, ["/a"])
})
