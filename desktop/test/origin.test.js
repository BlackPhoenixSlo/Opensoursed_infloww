const test = require("node:test");
const assert = require("node:assert");

const { originOf, isAppOrigin } = require("../lib/origin.js");

const APP = "https://app.example.com";

test("originOf parses, normalises a trailing slash and drops paths", () => {
  assert.strictEqual(originOf("https://app.example.com/"), APP);
  assert.strictEqual(originOf("https://app.example.com/inbox?x=1"), APP);
  assert.strictEqual(originOf("http://localhost:3001"), "http://localhost:3001");
});

test("originOf rejects empty, garbage, opaque and non-strings", () => {
  assert.strictEqual(originOf(""), null);
  assert.strictEqual(originOf("not a url"), null);
  assert.strictEqual(originOf("file:///tmp/x.html"), null);
  assert.strictEqual(originOf("about:blank"), null);
  assert.strictEqual(originOf(null), null);
  assert.strictEqual(originOf(undefined), null);
});

test("isAppOrigin matches the configured origin only, and denies when none is configured", () => {
  assert.strictEqual(isAppOrigin("https://app.example.com/", APP), true);
  assert.strictEqual(isAppOrigin("https://app.example.com/messages-pro/a/1", APP), true);
  assert.strictEqual(isAppOrigin("https://evil.example.com/", APP), false);
  assert.strictEqual(isAppOrigin("http://app.example.com/", APP), false);
  assert.strictEqual(isAppOrigin("", APP), false);
  assert.strictEqual(isAppOrigin("https://app.example.com/", null), false);
});
