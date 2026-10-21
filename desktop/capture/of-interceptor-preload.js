"use strict";

// OnlyFans capture interceptor — delivered as an Electron PRELOAD that runs in
// the page's MAIN world (the capture window sets contextIsolation:false), so it
// can monkey-patch XHR/fetch and webpackChunkof_vue at document-start WITHOUT
// Chrome DevTools Protocol.
//
// Why not CDP: Cloudflare (which fronts onlyfans.com) detects `debugger.attach`
// / Runtime.enable and hard-blocks it — that was the blank-window bug. A plain
// preload trips none of that.
//
// It captures the signed headers + webpack sign-rules (static_param from module
// 89668, start/end from 802313) and pushes each update to the main process via
// ipcRenderer. It also mirrors onto window.__inflowwReaCapture / postMessage as a
// fallback. It NEVER sends anything off-device — the shell does that, over the
// relay.

const { ipcRenderer } = require("electron");

(function () {
  var REQUIRED_HDRS = ["user-id", "x-bc", "x-of-rev", "sign", "time"];
  var lastSeen = {};
  var lastRules = {};

  function publish() {
    for (var i = 0; i < REQUIRED_HDRS.length; i++) {
      if (!lastSeen[REQUIRED_HDRS[i]]) return;
    }
    var payload = {
      url: lastSeen.__url || "https://onlyfans.com/api2/v2/users/me",
      headers: {
        "user-id": lastSeen["user-id"],
        "x-bc": lastSeen["x-bc"],
        "x-of-rev": lastSeen["x-of-rev"],
        sign: lastSeen["sign"],
        time: lastSeen["time"],
        "user-agent": lastSeen["user-agent"] || navigator.userAgent,
      },
      rules: {
        static_param: lastRules.static_param || null,
        start: lastRules.start || null,
        end: lastRules.end || null,
      },
      capturedAt: new Date().toISOString(),
    };
    try {
      window.__inflowwReaCapture = payload;
    } catch (_) {}
    try {
      ipcRenderer.send("of-capture:data", payload);
    } catch (_) {}
  }

  function recordHeader(name, value) {
    var lc = String(name || "").toLowerCase();
    if (!value) return;
    if (lc === "user-id") lastSeen["user-id"] = String(value);
    else if (lc === "x-bc") lastSeen["x-bc"] = String(value);
    else if (lc === "x-of-rev") lastSeen["x-of-rev"] = String(value);
    else if (lc === "sign") lastSeen["sign"] = String(value);
    else if (lc === "time") lastSeen["time"] = String(value);
    else if (lc === "user-agent") lastSeen["user-agent"] = String(value);
  }

  try {
    var _xhrOpen = XMLHttpRequest.prototype.open;
    var _xhrSetHeader = XMLHttpRequest.prototype.setRequestHeader;
    var _xhrSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) {
      this.__cl_url = typeof url === "string" ? url : "";
      return _xhrOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
      recordHeader(name, value);
      return _xhrSetHeader.call(this, name, value);
    };
    XMLHttpRequest.prototype.send = function () {
      var url = this.__cl_url;
      if (url && url.indexOf("/api2/v2/") !== -1) {
        lastSeen.__url = url;
        publish();
      }
      return _xhrSend.apply(this, arguments);
    };
  } catch (_) {}

  try {
    var _fetch = window.fetch;
    window.fetch = function (input, init) {
      try {
        var url = typeof input === "string" ? input : (input && input.url) || "";
        var hdrs = (init && init.headers) || (input && input.headers);
        if (hdrs) {
          if (typeof hdrs.forEach === "function") {
            hdrs.forEach(function (v, k) {
              recordHeader(k, v);
            });
          } else if (Array.isArray(hdrs)) {
            for (var i = 0; i < hdrs.length; i++) recordHeader(hdrs[i][0], hdrs[i][1]);
          } else {
            var keys = Object.keys(hdrs);
            for (var j = 0; j < keys.length; j++) recordHeader(keys[j], hdrs[keys[j]]);
          }
        }
        if (url && url.indexOf("/api2/v2/") !== -1) {
          lastSeen.__url = url;
          publish();
        }
      } catch (_) {}
      // Bind to window to avoid an "Illegal invocation" that would crash callers.
      return _fetch.apply(window, arguments);
    };
  } catch (_) {}

  // Passkeys: Electron ships navigator.credentials but no WebAuthn UI, so a
  // modal passkey request never settles (not even at its own timeout; measured
  // on Electron 43 / Chromium 150). OnlyFans' email -> NEXT step asks for one,
  // so NEXT spun forever and the password step never came. Reject it the way
  // Chrome does when the user dismisses the passkey sheet (NotAllowedError);
  // OnlyFans then falls back to the password step. Conditional (autofill)
  // requests are left alone: in Chrome they also just wait.
  try {
    var creds = navigator.credentials;
    var noPasskeyUi = function (orig) {
      return function (options) {
        if (options && options.publicKey && options.mediation !== "conditional") {
          return Promise.reject(new DOMException("The operation either timed out or was not allowed.", "NotAllowedError"));
        }
        return orig.apply(creds, arguments);
      };
    };
    if (creds && typeof creds.get === "function") creds.get = noPasskeyUi(creds.get);
    if (creds && typeof creds.create === "function") creds.create = noPasskeyUi(creds.create);
  } catch (_) {}

  try {
    var wpChunks = (self.webpackChunkof_vue = self.webpackChunkof_vue || []);
    var origPush = wpChunks.push.bind(wpChunks);
    wpChunks.push = function (chunk) {
      try {
        var modules = chunk && chunk[1];
        if (modules) {
          if (modules[89668]) {
            var origMod89668 = modules[89668];
            modules[89668] = function (module, exports, require) {
              origMod89668(module, exports, require);
              var origSha1 = module.exports;
              if (typeof origSha1 === "function") {
                var wrapped = function (input) {
                  var result = origSha1(input);
                  try {
                    if (typeof input === "string" && input.split("\n").length === 4) {
                      var sp = input.split("\n")[0];
                      if (sp && lastRules.static_param !== sp) {
                        lastRules.static_param = sp;
                        publish();
                      }
                    }
                  } catch (_) {}
                  return result;
                };
                for (var k in origSha1) {
                  if (Object.prototype.hasOwnProperty.call(origSha1, k)) wrapped[k] = origSha1[k];
                }
                if (origSha1.prototype) wrapped.prototype = origSha1.prototype;
                module.exports = wrapped;
              }
            };
          }
          if (modules[802313]) {
            var origMod802313 = modules[802313];
            modules[802313] = function (module, exports, require) {
              origMod802313(module, exports, require);
              if (exports && typeof exports.A === "function") {
                var origFn = exports.A;
                exports.A = function () {
                  var result = origFn.apply(this, arguments);
                  try {
                    if (result && typeof result === "object") {
                      var rkeys = Object.keys(result);
                      for (var i = 0; i < rkeys.length; i++) {
                        var v = result[rkeys[i]];
                        if (typeof v === "string" && v.split(":").length === 4) {
                          var parts = v.split(":");
                          var changed = false;
                          if (parts[0] && lastRules.start !== parts[0]) {
                            lastRules.start = parts[0];
                            changed = true;
                          }
                          if (parts[3] && lastRules.end !== parts[3]) {
                            lastRules.end = parts[3];
                            changed = true;
                          }
                          if (changed) publish();
                          break;
                        }
                      }
                    }
                  } catch (_) {}
                  return result;
                };
              }
            };
          }
        }
      } catch (_) {
        // Never let capture instrumentation break OnlyFans' own module loading.
      }
      return origPush(chunk);
    };
  } catch (_) {}
})();
