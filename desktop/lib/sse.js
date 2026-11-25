"use strict";


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
      // comment line (`: connected`, `: ping`)
      if (line.startsWith(":")) continue;
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

function backoffDelay(attempt, { baseMs = 1000, maxMs = 30000, random = Math.random } = {}) {
  const step = Math.min(maxMs, baseMs * 2 ** Math.min(Math.max(0, attempt), 20));
  return Math.round(step / 2 + random() * (step / 2));
}

// 401/403 won't fix itself in a second; kick() (a successful page load) retries sooner
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
    this.gen = 0;
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

  restart() {
    this.stop();
    this.lastEventId = null;
    this.attempt = 0;
    this.start();
  }

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
      outcome = "ended";
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
