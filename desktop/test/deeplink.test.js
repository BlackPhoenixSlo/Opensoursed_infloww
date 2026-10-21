const test = require("node:test");
const assert = require("node:assert");

const { parseDeepLink, deepLinkFromArgv, chatLinkForUrl } = require("../lib/deeplink.js");

const ORIGIN = "https://app.example.com";

test("parses a chat link into the same-origin Messages Pro path", () => {
  assert.strictEqual(parseDeepLink("inflowwww://chat/8000149/200000003"), "/messages-pro/8000149/200000003");
  assert.strictEqual(parseDeepLink("inflowwww://chat/8000149/900604711209099264/"), "/messages-pro/8000149/900604711209099264");
  assert.strictEqual(parseDeepLink("InflowWWW://chat/acct_1-a/42"), "/messages-pro/acct_1-a/42");
});

test("rejects everything that is not exactly chat/<aid>/<fan>", () => {
  const bad = [
    "",
    null,
    42,
    "inflowwww://chat/123",
    "inflowwww://chat/123/",
    "inflowwww://chat//456",
    "inflowwww://chat/123/456/789", // extra segment
    "inflowwww://chat/123/456/settings",
    "inflowwww://chat/../456", // traversal
    "inflowwww://chat/123/..",
    "inflowwww://chat/123/../../settings",
    "inflowwww://chat/..%2F..%2Fsettings/1", // encoded slashes
    "inflowwww://chat/123%2F456/789",
    "inflowwww://chat/123/456%2f",
    "inflowwww://chat/123/456?t=secret", // query
    "inflowwww://chat/123/456#x", // fragment
    "inflowwww://settings/123/456", // other host
    "inflowwww://evil.com/chat/123/456",
    "inflowwww://chat.evil.com/123/456",
    "inflowwww://user@chat/123/456",
    "inflowwww:chat/123/456",
    "https://chat/123/456", // other scheme
    "infloww://chat/123/456",
    "javascript://chat/123/456",
    "inflowwww://chat/123/456\n/x",
    `inflowwww://chat/${"1".repeat(65)}/456`,
  ];
  for (const raw of bad) assert.strictEqual(parseDeepLink(raw), null, String(raw));
});

test("finds the link among command-line arguments", () => {
  const argv = ["C:\\Inflowwww\\Inflowwww.exe", "--allow-file-access-from-files", "inflowwww://chat/1/2"];
  assert.strictEqual(deepLinkFromArgv(argv), "/messages-pro/1/2");
  assert.strictEqual(deepLinkFromArgv(["electron", ".", "--dev"]), null);
  assert.strictEqual(deepLinkFromArgv(["x", "inflowwww://chat/1/../2"]), null);
  assert.strictEqual(deepLinkFromArgv(undefined), null);
});

test("maps the main window's chat URL back to its app link", () => {
  assert.strictEqual(chatLinkForUrl(`${ORIGIN}/messages-pro/8000149/200000003`, ORIGIN), "inflowwww://chat/8000149/200000003");
  assert.strictEqual(chatLinkForUrl(`${ORIGIN}/messages-pro/8000149/200000003?window=1`, ORIGIN), "inflowwww://chat/8000149/200000003");
  // Round trip.
  const link = chatLinkForUrl(`${ORIGIN}/messages-pro/a_1/99`, ORIGIN);
  assert.strictEqual(`${ORIGIN}${parseDeepLink(link)}`, `${ORIGIN}/messages-pro/a_1/99`);
});

test("no app link off a chat or off the app origin", () => {
  for (const url of [
    `${ORIGIN}/inbox`,
    `${ORIGIN}/messages-pro`,
    `${ORIGIN}/messages-pro/8000149`,
    `${ORIGIN}/messages-pro/8000149/u/somefan`,
    `${ORIGIN}/messages-pro/1/2/3`,
    `${ORIGIN}/messages-pro/1%2F2/3`,
    "https://evil.example.com/messages-pro/1/2",
    "file:///messages-pro/1/2",
    "about:blank",
    "",
  ]) {
    assert.strictEqual(chatLinkForUrl(url, ORIGIN), null, url);
  }
  assert.strictEqual(chatLinkForUrl(`${ORIGIN}/messages-pro/1/2`, null), null);
});
