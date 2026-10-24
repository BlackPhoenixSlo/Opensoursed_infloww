const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");
const LOG = path.join(process.env.DEMO_SHOTS_TMP, "server-offhost.jsonl");
const LOOPBACK = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);
const log = (via, target) => {
  try { fs.appendFileSync(LOG, JSON.stringify({ process: "next", via, target, refused: true }) + "\n"); } catch {}
};
const realFetch = globalThis.fetch;
if (realFetch) {
  globalThis.fetch = function guardedFetch(input, init) {
    let url;
    try { url = new URL(typeof input === "string" || input instanceof URL ? String(input) : input.url); } catch { url = null; }
    if (url && !LOOPBACK.has(url.hostname)) {
      log("fetch", url.origin + url.pathname);
      return Promise.reject(new TypeError("demo-shots: off-host fetch refused: " + url.origin));
    }
    return realFetch.call(this, input, init);
  };
}
// request(url[, options][, cb]) or request(options[, cb]); options override the url, and no host means localhost.
function target(args, proto) {
  let host = "localhost", where = proto + "//localhost";
  const a = args[0];
  if (typeof a === "string" || a instanceof URL) {
    try { const u = new URL(String(a)); host = u.hostname; where = u.origin + u.pathname; } catch {}
  }
  const o = a && typeof a === "object" && !(a instanceof URL) ? a : args[1] && typeof args[1] === "object" ? args[1] : null;
  if (o && (o.hostname || o.host)) {
    host = String(o.hostname || o.host);
    if (host.split(":").length === 2) host = host.split(":")[0];
    where = proto + "//" + host + (o.path || "");
  }
  return { host, where };
}
for (const [mod, proto] of [[http, "http:"], [https, "https:"]]) {
  for (const name of ["request", "get"]) {
    const real = mod[name];
    mod[name] = function guardedRequest(...args) {
      const t = target(args, proto);
      if (!LOOPBACK.has(t.host)) {
        log(proto.slice(0, -1) + "." + name, t.where);
        throw new Error("demo-shots: off-host " + proto.slice(0, -1) + "." + name + " refused: " + t.host);
      }
      return real.apply(this, args);
    };
  }
}
