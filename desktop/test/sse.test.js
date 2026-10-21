"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { SseParser, SseClient, backoffDelay, AUTH_RETRY_MS } = require("../lib/sse");

test("parser: frames across chunk boundaries, comments, id-only frames", () => {
  const p = new SseParser();
  assert.deepEqual(p.feed(": connected\n\nid: 7.1\n\nid: 7.2\nevent: api2_chat"), [
    { id: "7.1", event: "message", data: null },
  ]);
  assert.deepEqual(p.feed('_message\ndata: {"a":1}\n\n: ping\n\nevent: ping\ndata: {}\n\n'), [
    { id: "7.2", event: "api2_chat_message", data: '{"a":1}' },
    { id: undefined, event: "ping", data: "{}" },
  ]);
});

test("parser: CRLF, multi-line data, no space after colon", () => {
  const p = new SseParser();
  assert.deepEqual(p.feed("event:x\r\ndata:one\r\ndata: two\r\n\r\n"), [
    { id: undefined, event: "x", data: "one\ntwo" },
  ]);
});

test("backoff: grows, jitters inside [step/2, step], caps", () => {
  assert.equal(backoffDelay(0, { random: () => 0 }), 500);
  assert.equal(backoffDelay(0, { random: () => 1 }), 1000);
  assert.equal(backoffDelay(3, { random: () => 0 }), 4000);
  assert.equal(backoffDelay(3, { random: () => 1 }), 8000);
  assert.equal(backoffDelay(50, { random: () => 1 }), 30000);
  assert.equal(backoffDelay(50, { random: () => 0 }), 15000);
  assert.equal(backoffDelay(-1, { random: () => 1 }), 1000);
});

// ── client ───────────────────────────────────────────────────────────────────

function streamOf(chunks) {
  const enc = new TextEncoder();
  return {
    ok: true,
    status: 200,
    body: (async function* () {
      for (const c of chunks) yield enc.encode(c);
    })(),
  };
}

function fakeTimers() {
  const pending = [];
  return {
    pending,
    setTimer: (fn, ms) => {
      const t = { fn, ms, cleared: false };
      pending.push(t);
      return t;
    },
    clearTimer: (t) => {
      if (t) t.cleared = true;
    },
    // The retry timers (not the stale timers, which are cleared).
    live: () => pending.filter((t) => !t.cleared),
  };
}

const tick = () => new Promise((r) => setImmediate(r));

test("client: dispatches JSON events, resumes with the last id, backs off on errors", async () => {
  const timers = fakeTimers();
  const calls = [];
  const events = [];
  const responses = [
    () => streamOf(['id: 1.5\n\nid: 1.6\nevent: api2_chat_message\ndata: {"x":1}\n\n', "event: ping\ndata: {}\n\n"]),
    () => Promise.reject(new Error("boom")),
    () => ({ ok: false, status: 502, body: null }),
  ];
  const client = new SseClient({
    fetchStream: (lastId) => {
      calls.push(lastId);
      return responses.shift()();
    },
    onEvent: (type, payload) => events.push([type, payload]),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
    random: () => 1,
  });

  client.start();
  await tick();
  await tick();
  assert.deepEqual(events, [["api2_chat_message", { x: 1 }], ["ping", {}]]);
  assert.equal(client.lastEventId, "1.6");

  // The stream ended cleanly → quick reconnect (attempt 0).
  let retry = timers.live().at(-1);
  assert.equal(retry.ms, 1000);
  retry.cleared = true;
  retry.fn();
  await tick();
  assert.deepEqual(calls, [null, "1.6"]);

  // A network error → attempt 0 then grows.
  retry = timers.live().at(-1);
  assert.equal(retry.ms, 1000);
  retry.cleared = true;
  retry.fn();
  await tick();
  retry = timers.live().at(-1);
  assert.equal(retry.ms, 2000); // the 502 counts as the next failure
  client.stop();
});

test("client: 401 waits long; kick() retries at once; stop() cancels", async () => {
  const timers = fakeTimers();
  let n = 0;
  const client = new SseClient({
    fetchStream: () => {
      n++;
      return { ok: false, status: 401, body: null };
    },
    onEvent: () => {},
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  client.start();
  await tick();
  assert.equal(timers.live().at(-1).ms, AUTH_RETRY_MS);
  client.kick();
  await tick();
  assert.equal(n, 2);
  client.stop();
  assert.equal(timers.live().length, 0);
  client.kick(); // stopped: no-op
  await tick();
  assert.equal(n, 2);
});

test("client: restart() forgets the resume point", async () => {
  const timers = fakeTimers();
  const calls = [];
  const client = new SseClient({
    fetchStream: (lastId) => {
      calls.push(lastId);
      return streamOf(["id: 9.9\n\n"]);
    },
    onEvent: () => {},
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  client.start();
  await tick();
  assert.equal(client.lastEventId, "9.9");
  client.restart();
  await tick();
  assert.deepEqual(calls.slice(0, 2), [null, null]);
  client.stop();
});
