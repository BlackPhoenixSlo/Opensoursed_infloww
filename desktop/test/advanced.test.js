const test = require("node:test");
const assert = require("node:assert");
const { DOH_SERVERS, readAdvanced, advancedPatch, applyBeforeReady, applyAfterReady } = require("../lib/advanced");

const mapStore = (obj) => ({ get: (k, d) => (k in obj ? obj[k] : d) });

test("defaults: hardware acceleration on, secure DNS off", () => {
  assert.deepStrictEqual(readAdvanced(mapStore({})), { hwAccel: true, secureDns: false });
  assert.deepStrictEqual(readAdvanced(mapStore({ hwAccel: false, secureDns: true })), { hwAccel: false, secureDns: true });
});

test("advancedPatch keeps only boolean fields", () => {
  assert.deepStrictEqual(advancedPatch({ hwAccel: false, secureDns: "yes", serverUrl: "x" }), { hwAccel: false });
  assert.deepStrictEqual(advancedPatch(null), {});
});

test("apply calls Electron only when the switch asks for it", () => {
  const calls = [];
  const app = {
    disableHardwareAcceleration: () => calls.push("noGpu"),
    configureHostResolver: (o) => calls.push(o),
  };
  applyBeforeReady(app, { hwAccel: true });
  applyAfterReady(app, { secureDns: false });
  assert.deepStrictEqual(calls, []);
  applyBeforeReady(app, { hwAccel: false });
  applyAfterReady(app, { secureDns: true });
  assert.deepStrictEqual(calls, ["noGpu", { secureDnsMode: "automatic", secureDnsServers: DOH_SERVERS }]);
  for (const s of DOH_SERVERS) assert.match(s, /^https:\/\/[^/]+\/dns-query$/);
});
