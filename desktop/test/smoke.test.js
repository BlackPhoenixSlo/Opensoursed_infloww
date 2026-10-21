const test = require("node:test");
const assert = require("node:assert");

test("lib modules load without electron", () => {
  assert.ok(require("../lib/badge.js"));
});
