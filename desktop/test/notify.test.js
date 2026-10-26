const test = require("node:test");
const assert = require("node:assert");

const {
  plainText,
  sameOriginPath,
  parsePayload,
  createNotifier,
  registerNotifyIpc,
  DEDUPE_MS,
  RATE_MAX,
  RATE_WINDOW_MS,
  MAX_TITLE,
} = require("../lib/notify.js");

const APP = "https://app.example.com";

function fakeElectron({ supported = true, throwOnShow = false } = {}) {
  const made = [];
  class FakeNotification {
    static isSupported() {
      return supported;
    }
    constructor(opts) {
      this.opts = opts;
      this.handlers = {};
      this.shown = false;
      made.push(this);
    }
    on(ev, fn) {
      this.handlers[ev] = fn;
    }
    show() {
      if (throwOnShow) throw new Error("boom");
      this.shown = true;
    }
  }
  return { FakeNotification, made };
}

test("plainText strips control characters, collapses whitespace and caps", () => {
  assert.strictEqual(plainText("a\n\tb\u0000c  d", 50), "a b c d");
  assert.strictEqual(plainText(42, 50), "");
  const long = plainText("x".repeat(500), MAX_TITLE);
  assert.strictEqual(long.length, MAX_TITLE);
  assert.ok(long.endsWith("…"));
});

test("sameOriginPath accepts app paths only", () => {
  assert.strictEqual(sameOriginPath("/messages-pro/a/1?refresh=media", APP), "/messages-pro/a/1?refresh=media");
  assert.strictEqual(sameOriginPath(`${APP}/inbox#x`, APP), "/inbox#x");
  assert.strictEqual(sameOriginPath("//evil.example.com/x", APP), null);
  assert.strictEqual(sameOriginPath("https://evil.example.com/x", APP), null);
  assert.strictEqual(sameOriginPath("javascript:alert(1)", APP), null);
  assert.strictEqual(sameOriginPath("file:///etc/passwd", APP), null);
  assert.strictEqual(sameOriginPath("", APP), null);
  assert.strictEqual(sameOriginPath("/x", null), null);
});

test("parsePayload requires a title and drops a foreign href", () => {
  assert.strictEqual(parsePayload(null, APP), null);
  assert.strictEqual(parsePayload({ title: "   " }, APP), null);
  assert.deepStrictEqual(parsePayload({ id: "m1", title: "Ann", body: "<b>hi</b>", href: "https://evil.x/" }, APP), {
    id: "m1",
    title: "Ann",
    body: "<b>hi</b>", // shown as plain text by the OS; never rendered as HTML
    path: null,
  });
});

test("show: builds a silent notification and click opens the validated path", () => {
  const { FakeNotification, made } = fakeElectron();
  const clicks = [];
  const n = createNotifier({ Notification: FakeNotification, onClick: (p) => clicks.push(p), now: () => 1000 });
  assert.strictEqual(n.show({ id: "m1", title: "Ann", body: "hi", href: "/messages-pro/a/1?fanTab=Ann" }, APP), true);
  assert.strictEqual(made.length, 1);
  assert.deepStrictEqual(made[0].opts, { title: "Ann", body: "hi", silent: true });
  assert.ok(made[0].shown);
  made[0].handlers.click();
  // The query is kept: `fanTab` makes Messages Pro open the Fan as a Fan tab.
  assert.deepStrictEqual(clicks, ["/messages-pro/a/1?fanTab=Ann"]);
});

test("show: a foreign href still notifies but click opens no path", () => {
  const { FakeNotification, made } = fakeElectron();
  const clicks = [];
  const n = createNotifier({ Notification: FakeNotification, onClick: (p) => clicks.push(p), now: () => 0 });
  assert.strictEqual(n.show({ id: "x", title: "T", href: "https://evil.example.com/" }, APP), true);
  made[0].handlers.click();
  assert.deepStrictEqual(clicks, [null]);
});

test("show: dedupes the same id until DEDUPE_MS passes", () => {
  const { FakeNotification, made } = fakeElectron();
  let t = 0;
  const n = createNotifier({ Notification: FakeNotification, onClick() {}, now: () => t });
  assert.strictEqual(n.show({ id: "m1", title: "A" }, APP), true);
  t = 500;
  assert.strictEqual(n.show({ id: "m1", title: "A" }, APP), false); // a popout's toaster
  assert.strictEqual(n.show({ id: "m2", title: "B" }, APP), true);
  t = DEDUPE_MS + 1;
  assert.strictEqual(n.show({ id: "m1", title: "A" }, APP), true);
  assert.strictEqual(made.length, 3);
});

test("show: rate-limits bursts across ids", () => {
  const { FakeNotification } = fakeElectron();
  let t = 0;
  const n = createNotifier({ Notification: FakeNotification, onClick() {}, now: () => t });
  for (let i = 0; i < RATE_MAX; i++) assert.strictEqual(n.show({ id: `b${i}`, title: "x" }, APP), true);
  assert.strictEqual(n.show({ id: "over", title: "x" }, APP), false);
  t = RATE_WINDOW_MS;
  assert.strictEqual(n.show({ id: "later", title: "x" }, APP), true);
});

test("show: unsupported platform or a throwing show returns false", () => {
  const a = fakeElectron({ supported: false });
  assert.strictEqual(createNotifier({ Notification: a.FakeNotification, onClick() {} }).show({ title: "x" }, APP), false);
  const b = fakeElectron({ throwOnShow: true });
  assert.strictEqual(createNotifier({ Notification: b.FakeNotification, onClick() {} }).show({ title: "x" }, APP), false);
});

test("registerNotifyIpc: only the configured app origin may notify", () => {
  const { FakeNotification, made } = fakeElectron();
  const handlers = {};
  const ipcMain = { handle: (ch, fn) => (handlers[ch] = fn) };
  let appOrigin = APP;
  registerNotifyIpc({ ipcMain, Notification: FakeNotification, getAppOrigin: () => appOrigin, onClick() {} });
  const call = (url, id) => handlers["shell:notify"]({ senderFrame: { url } }, { id, title: "T" });

  assert.strictEqual(call(`${APP}/inbox`, "a"), true);
  assert.strictEqual(call("https://evil.example.com/", "b"), false);
  assert.strictEqual(handlers["shell:notify"]({}, { id: "c", title: "T" }), false); // no sender frame
  appOrigin = null; // no server configured → denied
  assert.strictEqual(call(`${APP}/inbox`, "d"), false);
  assert.strictEqual(made.length, 1);
});
