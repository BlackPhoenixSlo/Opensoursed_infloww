const test = require("node:test");
const assert = require("node:assert");

const { createReloadLimiter, routeToRemember, WINDOW_MS } = require("../lib/recovery.js");

const ORIGIN = "https://app.example.com";

test("allows 3 reloads, then refuses until the 5-minute window slides", () => {
  let t = 1_000_000;
  const limiter = createReloadLimiter({ now: () => t });
  assert.strictEqual(limiter.tryReload(), true);
  t += 60_000;
  assert.strictEqual(limiter.tryReload(), true);
  t += 60_000;
  assert.strictEqual(limiter.tryReload(), true);
  t += 60_000;
  assert.strictEqual(limiter.tryReload(), false); // 4th within 5 min
  assert.strictEqual(limiter.tryReload(), false); // a refusal is not counted
  t = 1_000_000 + WINDOW_MS - 1;
  assert.strictEqual(limiter.tryReload(), false); // first is still inside the window
  t = 1_000_000 + WINDOW_MS;
  assert.strictEqual(limiter.tryReload(), true); // first one expired → one slot
  assert.strictEqual(limiter.tryReload(), false);
});

test("a fresh limiter after a long quiet spell allows the full cap again", () => {
  let t = 0;
  const limiter = createReloadLimiter({ now: () => t });
  for (let i = 0; i < 3; i++) assert.strictEqual(limiter.tryReload(), true);
  assert.strictEqual(limiter.tryReload(), false);
  t += WINDOW_MS * 2;
  for (let i = 0; i < 3; i++) assert.strictEqual(limiter.tryReload(), true);
  assert.strictEqual(limiter.tryReload(), false);
});

test("remembers same-origin routes with the share token stripped", () => {
  assert.strictEqual(routeToRemember(`${ORIGIN}/messages-pro/1/2`, ORIGIN), "/messages-pro/1/2");
  assert.strictEqual(routeToRemember(`${ORIGIN}/inbox?t=secret`, ORIGIN), "/inbox");
  assert.strictEqual(routeToRemember(`${ORIGIN}/vault-pro?tab=a&t=secret#x`, ORIGIN), "/vault-pro?tab=a");
  assert.strictEqual(routeToRemember(`${ORIGIN}/`, ORIGIN), "/");
});

test("ignores anything off the app origin", () => {
  for (const url of [
    "https://onlyfans.com/my/chats",
    "http://app.example.com/inbox", // other scheme → other origin
    "chrome-error://chromewebdata/",
    "about:blank",
    "file:///tmp/error.html",
    "not a url",
  ]) {
    assert.strictEqual(routeToRemember(url, ORIGIN), null, url);
  }
  assert.strictEqual(routeToRemember(`${ORIGIN}/inbox`, null), null);
});
