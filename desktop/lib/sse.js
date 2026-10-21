"use strict";

// A Server-Sent Events client for the MAIN process, so notifications and the
// badge keep working while the page is crashed, reloading or never loaded.
//
// It speaks to the relay's `/events` the way the page's EventSource does
// (lib/events.ts): the caller's `fetchStream` sends the partition's cookies
// and `?t=`, and the last `id:` it saw goes back as `Last-Event-ID`, so a
// reconnect gets the relay's replay (or a `resync` frame when the replay no
// longer reaches back). EventSource reconnects on its own; this does it by
// hand with exponential backoff, plus a stale timer, because a half-dead
// socket never errors: the relay pings every 20 s, so `staleMs` of silence
// means the pipe is gone.
//
// Electron-free on purpose: `fetchStream` and the timers are injected, so
// test/sse.test.js drives it with fakes.

// Frame parser for the text/event-stream wire format. Feed it decoded text in
// any chunking; it returns the frames completed so far. A frame with only an
// `id:` (the relay sends one naming its head at connect) has data null: it
// moves the resume point but is not an event.
class SseParser {
  constructor() {
    this.buf = "";
    this.id = undefined;
    this.event = "";
    this.data = [];
  }

  feed(text) {
    this.buf += text;
    const frames = [];
    let nl;
    while ((nl = this.buf.indexOf("\n")) !== -1) {
      let line = this.buf.slice(0, nl);
      this.buf = this.buf.slice(nl + 1);
      if (line.endsWith("\r")) line = line.slice(0, -1);
      if (line === "") {
        if (this.id !== undefined || this.data.length) {
          frames.push({
            id: this.id,
            event: this.event || "message",
            data: this.data.length ? this.data.join("\n") : null,
          });
        }
        this.id = undefined;
        this.event = "";
        this.data = [];
        continue;
      }
      if (line.startsWith(":")) continue; // comment (`: connected`, `: ping`)
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "data") this.data.push(value);
      else if (field === "event") this.event = value;
      else if (field === "id" && !value.includes("\0")) this.id = value;
    }
    return frames;
  }
}

// Exponential backoff with "equal jitter": half the step is fixed, half
// random, so a relay restart doesn't get every desktop back in the same
// millisecond. attempt 0 → 0.5–1 s, then 1–2 s, 2–4 s … capped at maxMs.
function backoffDelay(attempt, { baseMs = 1000, maxMs = 30000, random = Math.random } = {}) {
  const step = Math.min(maxMs, baseMs * 2 ** Math.min(Math.max(0, attempt), 20));
  return Math.round(step / 2 + random() * (step / 2));
}

// Signed out (401) or not allowed (403) won't fix itself in a second; wait
// long, and let `kick()` (a successful page load) retry sooner.
const AUTH_RETRY_MS = 60000;

class SseClient {
  /**
   * @param {object} o
   * @param {(lastEventId: string|null, signal: AbortSignal) => Promise<{ok:boolean,status:number,body:AsyncIterable<Uint8Array>}>} o.fetchStream
   * @param {(type: string, payload: any) => void} o.onEvent  every frame with data, JSON-parsed
   * @param {(msg: string) => void} [o.log]
   */
  constructor({ fetchStream, onEvent, log = () => {}, staleMs = 60000, setTimer = setTimeout, clearTimer = clearTimeout, random = Math.random }) {
    this.fetchStream = fetchStream;
    this.onEvent = onEvent;
    this.log = log;
    this.staleMs = staleMs;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.random = random;
    this.running = false;
    this.gen = 0; //            bumps on stop/restart; an older loop sees it and quits
    this.attempt = 0;
    this.lastEventId = null;
    this.controller = null;
    this.retryTimer = null;
    this.connected = false;
  }

  start() {
    if (this.running) return;
    this.running = true;
    this._connect(++this.gen);
  }

  stop() {
    this.running = false;
    this.gen++;
    this.connected = false;
    this.clearTimer(this.retryTimer);
    this.retryTimer = null;
    if (this.controller) this.controller.abort();
    this.controller = null;
  }

  // New server or token: the old resume point means nothing there.
  restart() {
    this.stop();
    this.lastEventId = null;
    this.attempt = 0;
    this.start();
  }

  // Retry now if we're waiting out a backoff (the page just loaded, the
  // machine woke up). A live connection is left alone.
  kick() {
    if (!this.running || !this.retryTimer) return;
    this.clearTimer(this.retryTimer);
    this.retryTimer = null;
    this.attempt = 0;
    this._connect(this.gen);
  }

  async _connect(gen) {
    this.retryTimer = null;
    const controller = new AbortController();
    this.controller = controller;
    let staleTimer = null;
    const armStale = () => {
      this.clearTimer(staleTimer);
      staleTimer = this.setTimer(() => controller.abort(), this.staleMs);
    };
    let outcome = "error";
    try {
      armStale();
      const res = await this.fetchStream(this.lastEventId, controller.signal);
      if (gen !== this.gen) return;
      if (!res.ok) {
        outcome = res.status === 401 || res.status === 403 ? "auth" : "error";
        this.log(`[sse] HTTP ${res.status}`);
        return;
      }
      this.connected = true;
      this.attempt = 0;
      const parser = new SseParser();
      const decoder = new TextDecoder();
      for await (const chunk of res.body) {
        if (gen !== this.gen) return;
        armStale();
        for (const f of parser.feed(decoder.decode(chunk, { stream: true }))) {
          if (f.id !== undefined) this.lastEventId = f.id;
          if (f.data === null) continue;
          let payload;
          try {
            payload = JSON.parse(f.data);
          } catch {
            payload = { __raw: f.data };
          }
          try {
            this.onEvent(f.event, payload);
          } catch (err) {
            this.log(`[sse] listener error: ${err && err.message}`);
          }
        }
      }
      outcome = "ended"; // the relay closed it (e.g. after assignment_changed)
    } catch (err) {
      if (gen === this.gen) this.log(`[sse] ${controller.signal.aborted ? "stale, reconnecting" : `error: ${err && err.message}`}`);
    } finally {
      this.clearTimer(staleTimer);
      if (gen === this.gen) {
        this.connected = false;
        this._scheduleRetry(gen, outcome);
      }
    }
  }

  _scheduleRetry(gen, outcome) {
    if (!this.running || gen !== this.gen) return;
    const delay =
      outcome === "auth"
        ? AUTH_RETRY_MS
        : backoffDelay(outcome === "ended" ? 0 : this.attempt++, { random: this.random });
    this.retryTimer = this.setTimer(() => this._connect(gen), delay);
  }
}

module.exports = { SseParser, SseClient, backoffDelay, AUTH_RETRY_MS };
