"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { DEFAULT_SETTINGS, parseSettings, shouldPing, noticesFor, SeenKeys } = require("../lib/relay-notices");

const path = require("node:path");
const fs = require("node:fs");

// One notice shape, three parsers: the page's (canonical), this one and the relay's push.
const FIXTURE = path.join(__dirname, "..", "..", "service", "tests", "fixtures", "notice_cases.json");
const { cases } = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));

const frameType = (frame) => Object.keys(frame).find((k) => !k.startsWith("__"));

test("notice_cases.json: the page's notices, gated by the same settings", () => {
  assert.ok(cases.length >= 15);
  for (const c of cases) {
    const settings = parseSettings(JSON.stringify(c.settings || {}));
    const got = noticesFor(frameType(c.frame), c.frame).filter((n) => shouldPing(settings, n.typeKey));
    assert.deepEqual(got, c.expect, c.name);
  }
});

test("a tip DM is a tip notice with its amount; the title falls back to the brand passed in", () => {
  const env = { __account_id: "100", api2_chat_message: { id: 9, isTip: true, tipAmount: 12, price: 0, fromUser: { id: 5 } } };
  assert.deepEqual(noticesFor("api2_chat_message", env, "Example App"), [{
    id: "100:m9",
    typeKey: "tip",
    title: "Example App",
    body: "Tipped you $12",
    href: "/messages-pro/100/5?refresh=media&fanTab=fan+5",
  }]);
  const free = { ...env, api2_chat_message: { ...env.api2_chat_message, tipAmount: 0 } };
  assert.equal(noticesFor("api2_chat_message", free)[0].body, "Sent you a tip");
});

test("events without an account or of other types are ignored", () => {
  assert.deepEqual(noticesFor("api2_chat_message", { api2_chat_message: { id: 1, fromUser: { id: 2 } } }), []);
  assert.deepEqual(noticesFor("ping", { __account_id: "1" }), []);
  assert.deepEqual(noticesFor("resync", {}), []);
});

test("settings: the app's stored JSON over the defaults; the gate", () => {
  assert.equal(parseSettings(null), DEFAULT_SETTINGS);
  assert.equal(parseSettings("{bad json"), DEFAULT_SETTINGS);
  const s = parseSettings(JSON.stringify({ toast: { message: true }, osPing: true }));
  assert.equal(s.toast.message, true);
  assert.equal(s.toast.tip, true);
  assert.equal(shouldPing(s, "message"), true);
  assert.equal(shouldPing(DEFAULT_SETTINGS, "message"), false); // off by default, as in the app
  assert.equal(shouldPing(DEFAULT_SETTINGS, "purchases"), true);
  assert.equal(shouldPing({ ...s, enabled: false }, "message"), false);
  assert.equal(shouldPing({ ...s, osPing: false }, "message"), false);
  assert.equal(shouldPing(s, null), false);
});

test("seen keys dedupe and stay bounded", () => {
  const seen = new SeenKeys(2);
  assert.equal(seen.claim("a"), true);
  assert.equal(seen.claim("a"), false);
  seen.claim("b");
  seen.claim("c"); // evicts "a"
  assert.equal(seen.claim("a"), true);
});
