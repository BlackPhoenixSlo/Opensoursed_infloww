"use strict";

// Settings → Advanced options: hardware acceleration and secure DNS. Both are
// support fixes (GPU crashes / blank windows; an ISP DNS that blocks or hijacks
// our host) and both only take effect on the next launch, hence the Restart
// button in the Settings window.

// DoH resolvers, in Infloww's order (findings 02 M14). levonet is left out: we
// could not confirm its endpoint. Plain URLs = Chromium uses POST.
const DOH_SERVERS = [
  "https://1.1.1.1/dns-query",
  "https://unfiltered.adguard-dns.com/dns-query",
  "https://doh.dns.sb/dns-query",
  "https://dns.google/dns-query",
  "https://dns.quad9.net/dns-query",
  "https://doh.opendns.com/dns-query",
];

function readAdvanced(store) {
  return {
    hwAccel: store.get("hwAccel", true) !== false, // default on
    secureDns: store.get("secureDns", false) === true, // default off
  };
}

// Persist only the fields that were sent, coerced to booleans.
function advancedPatch(incoming) {
  const patch = {};
  if (incoming && typeof incoming.hwAccel === "boolean") patch.hwAccel = incoming.hwAccel;
  if (incoming && typeof incoming.secureDns === "boolean") patch.secureDns = incoming.secureDns;
  return patch;
}

// Must run before app ready.
function applyBeforeReady(app, prefs) {
  if (!prefs.hwAccel) app.disableHardwareAcceleration();
}

// Must run after app ready. 'automatic' = DoH first, plain DNS if every DoH
// server is unreachable, so a network that blocks DoH still connects.
function applyAfterReady(app, prefs) {
  if (!prefs.secureDns) return;
  try {
    app.configureHostResolver({ secureDnsMode: "automatic", secureDnsServers: DOH_SERVERS });
  } catch (err) {
    console.warn("[advanced] configureHostResolver failed:", err && err.message);
  }
}

module.exports = { DOH_SERVERS, readAdvanced, advancedPatch, applyBeforeReady, applyAfterReady };
