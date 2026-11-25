(function () {
  "use strict";

  const REQUIRED_HDRS = ["user-id", "x-bc", "x-of-rev", "sign", "time"];
  const lastSeen = {};
  const lastRules = {};
  const lastIdent = {};

  // Sniff replies, not our own requests: every OF call must be signed and we cannot mint a signature.
  function dbg() {
    try {
      if (window.__chatterlyDebug) console.log("[Chatterly]", ...arguments);
    } catch (_) {}
  }

  function noteIdentity(url, text) {
    try {
      if (!text || lastIdent.username) return;
      const c = text.charAt(0);
      if (c !== "{" && c !== "[") return;
      if (text.indexOf('"username"') === -1) return;
      const body = JSON.parse(text);

      if (takeSelfMarked(body, 0)) {
        dbg("labelled from self-marker in", url);
        publish();
        return;
      }

      // Id match keeps this honest: payloads hold other people's accounts; only ours may set the label.
      const selfId = lastSeen["user-id"];
      if (!selfId) {
        stashCandidates(text);
        dbg("no user-id yet, stashed candidates", url);
        return;
      }
      const hit = takeIdentity(body, String(selfId), 0);
      dbg(hit ? "labelled from id-match" : "no self-match in", url, "self=" + selfId);
      if (lastIdent.username || lastIdent.name) publish();
    } catch (e) {
      dbg("parse failed for", url, e && e.message);
    }
  }

  function takeSelfMarked(node, depth) {
    if (!node || typeof node !== "object" || depth > 4) return false;
    if (Array.isArray(node)) {
      for (const item of node) if (takeSelfMarked(item, depth + 1)) return true;
      return false;
    }
    if (node.isAuth === true && node.username) {
      lastIdent.username = String(node.username);
      if (node.name) lastIdent.name = String(node.name);
      if (node.id != null && !lastSeen["user-id"]) lastSeen["user-id"] = String(node.id);
      return true;
    }
    for (const k of Object.keys(node)) {
      const v = node[k];
      if (v && typeof v === "object" && takeSelfMarked(v, depth + 1)) return true;
    }
    return false;
  }

  const pending = {};

  function stashCandidates(text) {
    try {
      if (text.indexOf('"username"') === -1) return;
      collect(JSON.parse(text), 0);
    } catch (_) {}
  }

  function collect(node, depth) {
    if (!node || typeof node !== "object" || depth > 4) return;
    if (Array.isArray(node)) {
      for (const item of node) collect(item, depth + 1);
      return;
    }
    if (node.username && node.id != null && Object.keys(pending).length < 50) {
      pending[String(node.id)] = { username: String(node.username), name: node.name ? String(node.name) : null };
    }
    for (const k of Object.keys(node)) {
      const v = node[k];
      if (v && typeof v === "object") collect(v, depth + 1);
    }
  }

  function resolveIdentity() {
    if (lastIdent.username) return;
    const selfId = lastSeen["user-id"];
    if (!selfId) return;
    const hit = pending[String(selfId)];
    if (!hit) return;
    lastIdent.username = hit.username;
    if (hit.name) lastIdent.name = hit.name;
    dbg("labelled from stashed candidate", selfId);
    publish();
  }

  function takeIdentity(node, selfId, depth) {
    if (!node || typeof node !== "object" || depth > 4) return false;
    if (Array.isArray(node)) {
      for (const item of node) if (takeIdentity(item, selfId, depth + 1)) return true;
      return false;
    }
    if (node.username && String(node.id) === selfId) {
      lastIdent.username = String(node.username);
      if (node.name) lastIdent.name = String(node.name);
      return true;
    }
    for (const k of Object.keys(node)) {
      const v = node[k];
      if (v && typeof v === "object" && takeIdentity(v, selfId, depth + 1)) return true;
    }
    return false;
  }

  function publish() {
    for (const k of REQUIRED_HDRS) if (!lastSeen[k]) return;
    try {
      window.postMessage(
        {
          __chatterly_capture: true,
          payload: {
            url: lastSeen.__url || "https://onlyfans.com/api2/v2/users/me",
            headers: {
              "user-id":    lastSeen["user-id"],
              "x-bc":       lastSeen["x-bc"],
              "x-of-rev":   lastSeen["x-of-rev"],
              "sign":       lastSeen["sign"],
              "time":       lastSeen["time"],
              "user-agent": lastSeen["user-agent"] || navigator.userAgent,
            },
            rules: {
              static_param: lastRules.static_param || null,
              start:        lastRules.start || null,
              end:          lastRules.end || null,
            },
            username: lastIdent.username || null,
            displayName: lastIdent.name || null,
            capturedAt: new Date().toISOString(),
          },
        },
        location.origin
      );
    } catch (_) {}
  }

  function recordHeader(name, value) {
    const lc = String(name || "").toLowerCase();
    if (!value) return;
    if (lc === "user-id") {
      const had = lastSeen["user-id"];
      lastSeen["user-id"] = String(value);
      if (!had) resolveIdentity();
    }
    else if (lc === "x-bc")       lastSeen["x-bc"]       = String(value);
    else if (lc === "x-of-rev")   lastSeen["x-of-rev"]   = String(value);
    else if (lc === "sign")       lastSeen["sign"]       = String(value);
    else if (lc === "time")       lastSeen["time"]       = String(value);
    else if (lc === "user-agent") lastSeen["user-agent"] = String(value);
  }

  const _xhrOpen = XMLHttpRequest.prototype.open;
  const _xhrSetHeader = XMLHttpRequest.prototype.setRequestHeader;
  const _xhrSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__cl_url = typeof url === "string" ? url : "";
    return _xhrOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
    recordHeader(name, value);
    return _xhrSetHeader.call(this, name, value);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    const url = this.__cl_url;
    if (url && url.includes("/api2/v2/")) {
      lastSeen.__url = url;
      publish();
      try {
        this.addEventListener("load", () => {
          try {
            if (this.responseType === "" || this.responseType === "text") {
              noteIdentity(url, this.responseText);
            }
          } catch (_) {}
        });
      } catch (_) {}
    }
    return _xhrSend.apply(this, args);
  };

  const _fetch = window.fetch;
  window.fetch = function (input, init) {
    try {
      const url = typeof input === "string" ? input : (input && input.url) || "";
      const hdrs = (init && init.headers) || (input && input.headers);
      if (hdrs) {
        if (typeof hdrs.forEach === "function") {
          hdrs.forEach((v, k) => recordHeader(k, v));
        } else if (Array.isArray(hdrs)) {
          for (const [k, v] of hdrs) recordHeader(k, v);
        } else {
          for (const k of Object.keys(hdrs)) recordHeader(k, hdrs[k]);
        }
      }
      if (url && url.includes("/api2/v2/")) {
        lastSeen.__url = url;
        publish();
      }
    } catch (_) {}
    const p = _fetch.apply(this, arguments);
    try {
      const u = typeof input === "string" ? input : (input && input.url) || "";
      if (u && u.includes("/api2/v2/")) {
        // .clone() so the page's own reader still gets an unconsumed body.
        return p.then((res) => {
          try { res.clone().text().then((t) => noteIdentity(u, t)).catch(() => {}); } catch (_) {}
          return res;
        });
      }
    } catch (_) {}
    return p;
  };


  const wpChunks = (self.webpackChunkof_vue = self.webpackChunkof_vue || []);
  const origPush = wpChunks.push.bind(wpChunks);

  wpChunks.push = function (chunk) {
    const modules = chunk[1];
    if (!modules) return origPush(chunk);

    // static_param rotates per frontend deploy and is imported at runtime; hooking js-sha1 reads it on the first sign().
    if (modules[89668]) {
      const origMod = modules[89668];
      modules[89668] = function (module, exports, require) {
        origMod(module, exports, require);
        const origSha1 = module.exports;
        if (typeof origSha1 === "function") {
          const wrapped = function (input) {
            const result = origSha1(input);
            try {
              if (typeof input === "string" && input.split("\n").length === 4) {
                const staticParam = input.split("\n")[0];
                if (staticParam && lastRules.static_param !== staticParam) {
                  lastRules.static_param = staticParam;
                  publish();
                }
              }
            } catch (_) {}
            return result;
          };
          for (const k of Object.keys(origSha1)) wrapped[k] = origSha1[k];
          if (origSha1.prototype) wrapped.prototype = origSha1.prototype;
          module.exports = wrapped;
        }
      };
    }

    if (modules[802313]) {
      const origMod = modules[802313];
      modules[802313] = function (module, exports, require) {
        origMod(module, exports, require);
        if (exports && typeof exports.A === "function") {
          const origFn = exports.A;
          exports.A = function (...args) {
            const result = origFn.apply(this, args);
            try {
              if (result && typeof result === "object") {
                for (const k of Object.keys(result)) {
                  const v = result[k];
                  if (typeof v === "string" && v.split(":").length === 4) {
                    const [start, , , end] = v.split(":");
                    let changed = false;
                    if (start && lastRules.start !== start) { lastRules.start = start; changed = true; }
                    if (end   && lastRules.end   !== end)   { lastRules.end   = end;   changed = true; }
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

    return origPush(chunk);
  };
})();
