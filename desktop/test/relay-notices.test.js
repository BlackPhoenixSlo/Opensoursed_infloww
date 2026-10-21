"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { DEFAULT_SETTINGS, parseSettings, shouldPing, noticesFor, SeenKeys } = require("../lib/relay-notices");

test("an inbound DM is a message notice with the page's id and href; our own send is not", () => {
  const env = {
    __account_id: "100",
    api2_chat_message: { id: 55, text: "<p>hey <b>you</b></p>", fromUser: { id: 777, name: "Fan" } },
  };
  assert.deepEqual(noticesFor("api2_chat_message", env), [{
    id: "100:m55",
    typeKey: "message",
    title: "Fan",
    body: "hey you",
    href: "/messages-pro/100/777",
  }]);
  const out = { __account_id: "100", api2_chat_message: { id: 56, text: "hi", fromUser: { id: "100" } } };
  assert.deepEqual(noticesFor("api2_chat_message", out), []);
  const media = { __account_id: "100", api2_chat_message: { id: 57, text: "", mediaCount: 2, fromUser: { id: 9 } } };
  assert.equal(noticesFor("api2_chat_message", media)[0].body, "Sent you media");
});

test("a PPV unlock and OF toasts; money links refresh the chat's media", () => {
  const buy = { __account_id: "100", purchase_notified: { notif_id: "n1", fan_id: 9, amount_cents: 1250, name: "Bob" } };
  const [n] = noticesFor("purchase_notified", buy);
  assert.equal(n.id, "100:n1");
  assert.equal(n.typeKey, "purchases");
  assert.equal(n.body, "Unlocked your PPV — $12.50");
  assert.equal(n.href, "/messages-pro/100/9?refresh=media");

  const toasts = {
    __account_id: "100",
    toasts: [
      { id: 1, type: "tip", text: "{RELATED_USER_NAME} tipped $5", data: { replacements: { "{RELATED_USER_NAME}": "Ann", "{RELATED_USER_ID}": "42" } } },
      { id: 2, type: "unknown_kind", text: "x" },
      { type: "tip" },
      { id: 3, type: "subscribed", text: "New subscriber" },
    ],
  };
  assert.deepEqual(noticesFor("toasts", toasts).map((t) => [t.id, t.typeKey, t.title, t.body, t.href]), [
    ["100:1", "tip", "Ann", "Ann tipped $5", "/messages-pro/100/42?refresh=media"],
    ["100:3", "subscribed", "Inflowwww", "New subscriber", null],
  ]);
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
