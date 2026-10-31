// The app's real EventBus (app/lib/events.ts + eventBusReducer.ts) on a real /events
// stream, through lib/app_ts.py (the app's own TypeScript in node). The bus reconnects,
// backs off, pauses and resumes exactly as in the browser; only its socket is node's:
//
//   EventSource: a spec-following one over fetch (per-run cookie, the relay's URL; the
//     browser's own reconnect after a dropped socket sends Last-Event-ID, a non-200 fails
//     the connection: readyState CLOSED + error, so the bus's backoff takes over). A
//     wire-level outage (`refuse`) answers the next N connects as a relay down behind its
//     proxy does (a non-200), without reaching the relay.
//   Timers: the bus's retry timers (setTimeout >= RETRY_MIN_MS called from lib/events.ts)
//     run `scale` times faster; the delay the bus asked for is what is recorded.
//   No requestAnimationFrame (as a hidden tab): queued events flush on APPLY_WINDOW_MS.
//
// Input: {base, cookie, scope, warm_ms, outages: [refusals, ...], pause_ms, tail_ms,
//         reconnect_ms, scale, timeout_ms}
// Plan: open; once connected and `warm_ms` passed, for each outage: drop the socket under
//   the browser and refuse that many connects, then wait until the bus is connected again;
//   then pause `pause_ms` and resume; then `tail_ms` more; then pause (closes).
// Output: {got: [api2_chat_message ids, in the order listeners got them], resync, errors,
//          retries: [ms the bus armed, in order], opens: [url, ...], refused, phases, consts}
export async function run(load, input) {
  const realSetTimeout = globalThis.setTimeout;
  const realSetInterval = globalThis.setInterval;
  const red = await load("/lib/eventBusReducer.ts");
  const retries = [];
  const intervals = [];
  const fromBus = () => /[\\/]lib[\\/]events\.ts/.test(new Error().stack || "");
  globalThis.setTimeout = (fn, ms = 0, ...a) => {
    if (ms >= red.RETRY_MIN_MS && fromBus()) {
      retries.push(ms);
      ms = ms / input.scale;
    }
    return realSetTimeout(fn, ms, ...a);
  };
  globalThis.setInterval = (fn, ms, ...a) => {
    const h = realSetInterval(fn, ms, ...a);
    if (fromBus()) intervals.push(h);
    return h;
  };

  const world = { refuse: 0, refused: 0, opens: [], sockets: [] };
  const base = input.base;
  const cookie = input.cookie;

  class NodeEventSource {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSED = 2;

    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.onopen = this.onmessage = this.onerror = null;
      this.lastEventId = "";
      this.reconnectMs = input.reconnect_ms;
      this._l = new Map();
      this._ac = null;
      world.opens.push(url);
      world.sockets.push(this);
      queueMicrotask(() => this._connect());
    }

    addEventListener(type, fn) {
      if (!this._l.has(type)) this._l.set(type, []);
      this._l.get(type).push(fn);
    }

    close() {
      this.readyState = 2;
      this._ac?.abort();
    }

    /** The socket dies under the browser (a network blip, the relay's proxy restarting). */
    drop() {
      if (this.readyState !== 1) return false;
      const ac = this._ac;
      this._ac = null;
      ac?.abort();
      this._reconnectLater();
      return true;
    }

    _fire(type, ev) {
      if (type === "open") this.onopen?.(ev);
      else if (type === "error") this.onerror?.(ev);
      else if (type === "message") this.onmessage?.(ev);
      for (const fn of this._l.get(type) || []) fn(ev);
    }

    _fail() {
      this.readyState = 2;
      this._fire("error", { type: "error" });
    }

    _reconnectLater() {
      if (this.readyState === 2) return;
      this.readyState = 0;
      this._fire("error", { type: "error" });
      realSetTimeout(() => this._connect(), this.reconnectMs);
    }

    async _connect() {
      if (this.readyState === 2) return;
      if (world.refuse > 0) {
        world.refuse -= 1;
        world.refused += 1;
        this._fail();
        return;
      }
      const ac = new AbortController();
      this._ac = ac;
      const headers = { cookie, accept: "text/event-stream" };
      if (this.lastEventId) headers["last-event-id"] = this.lastEventId;
      let r;
      try {
        r = await fetch(new URL(this.url, base), { headers, signal: ac.signal });
      } catch {
        if (this._ac === ac) this._reconnectLater();
        return;
      }
      if (this._ac !== ac || this.readyState === 2) return;
      if (r.status !== 200) {
        this._fail();
        return;
      }
      this.readyState = 1;
      this._fire("open", { type: "open" });
      const dec = new TextDecoder();
      let buf = "";
      let event = "";
      let data = [];
      try {
        for await (const chunk of r.body) {
          if (this._ac !== ac) return;
          buf += dec.decode(chunk, { stream: true });
          let nl;
          while ((nl = buf.search(/\r\n|\r|\n/)) >= 0) {
            const line = buf.slice(0, nl);
            buf = buf.slice(nl + (buf.startsWith("\r\n", nl) ? 2 : 1));
            if (line === "") {
              if (data.length) {
                const type = event || "message";
                this._fire(type, { type, data: data.join("\n"), lastEventId: this.lastEventId });
              }
              event = "";
              data = [];
              continue;
            }
            if (line.startsWith(":")) continue;
            const i = line.indexOf(":");
            const field = i < 0 ? line : line.slice(0, i);
            let value = i < 0 ? "" : line.slice(i + 1);
            if (value.startsWith(" ")) value = value.slice(1);
            if (field === "event") event = value;
            else if (field === "data") data.push(value);
            else if (field === "id" && !value.includes("\0")) this.lastEventId = value;
            else if (field === "retry" && /^\d+$/.test(value)) this.reconnectMs = Number(value);
          }
        }
      } catch {
        /* aborted (ours) or the socket died */
      }
      if (this._ac === ac) this._reconnectLater();
    }
  }
  globalThis.EventSource = NodeEventSource;

  const { eventBus } = await load("/lib/events.ts");
  const got = [];
  let resync = 0;
  let errors = 0;
  eventBus.on("api2_chat_message", (e) => {
    const id = e?.api2_chat_message?.id;
    if (id != null) got.push(Number(id));
  });
  eventBus.on("resync", () => { resync += 1; });
  eventBus.on("__error", () => { errors += 1; });

  const t0 = Date.now();
  const phases = [];
  const sleep = (ms) => new Promise((r) => realSetTimeout(r, ms));
  const until = async (what, ok) => {
    const end = Date.now() + input.timeout_ms;
    while (!ok()) {
      if (Date.now() > end) throw new Error(`events_ts: timed out waiting for ${what}`);
      await sleep(20);
    }
  };
  const mark = (name) => phases.push([name, Date.now() - t0, got.length]);
  const current = () => world.sockets[world.sockets.length - 1];

  try {
    eventBus.setScope(input.scope);
    await until("the first connect", () => eventBus.isConnected());
    mark("connected");
    await sleep(input.warm_ms);
    for (const n of input.outages) {
      world.refuse = n;
      if (!current().drop()) throw new Error("events_ts: no open socket to drop");
      mark(`drop+refuse ${n}`);
      await until("the reopen after the outage", () => world.refuse === 0 && eventBus.isConnected());
      mark("reconnected");
      await sleep(input.warm_ms);
    }
    eventBus.pause();
    mark("paused");
    await sleep(input.pause_ms);
    eventBus.resume();
    await until("the reopen after resume", () => eventBus.isConnected());
    mark("resumed");
    await sleep(input.tail_ms);
    mark("end");
  } finally {
    eventBus.pause();
    for (const h of intervals) clearInterval(h);
    globalThis.setTimeout = realSetTimeout;
    globalThis.setInterval = realSetInterval;
  }
  return {
    got, resync, errors, retries, opens: world.opens, refused: world.refused, phases,
    consts: { retry_min_ms: red.RETRY_MIN_MS, retry_max_ms: red.RETRY_MAX_MS },
  };
}
