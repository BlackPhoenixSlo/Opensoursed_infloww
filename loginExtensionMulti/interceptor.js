// MAIN-world interceptor — runs at document_start on onlyfans.com.
//
// Captures two classes of data the relay needs:
//
//   1. Header values from outgoing XHR/fetch on /api2/v2/*:
//        user-id, x-bc, x-of-rev, sign, time, user-agent
//      These are what the curl-from-DevTools already carries; we just
//      keep the latest set so the popup can emit a curl any time.
//
//   2. Runtime-only signing fields that the curl from DevTools does NOT
//      carry, but the relay needs to verify+resign requests at a fresh
//      OF revision:
//        static_param  — first line of the sha1 input inside chunk 2313.js
//        start, end    — the literal prefix/suffix in the produced sign
//      OF's `static_param` rotates per frontend deploy and is imported
//      from another module at runtime. The relay can't see it from the
//      wire alone, which is why a brand-new x-of-rev fails the
//      paste-curl flow with "no static_param available". Hooking the
//      js-sha1 module (webpack id 89668) lets us read it the moment the
//      page calls sign() for the first time.
//
// Strategy mirrors theOFchrackedextension/interceptor.js — that one is
// proven to work and we keep both in sync.

(function () {
  "use strict";

  const REQUIRED_HDRS = ["user-id", "x-bc", "x-of-rev", "sign", "time"];
  const lastSeen = {};
  const lastRules = {};  // static_param, start, end
  const lastIdent = {};  // username, name — read off /users/me responses

  // Pull the signed-in creator's handle out of an API response so the popup can
  // label a saved login "@handle" instead of a bare numeric user-id.
  // Response-sniffing (not a request of our own) because every OF call must be
  // signed, and we cannot mint a signature here.
  //
  // /users/me is the obvious source but not a reliable one: the SPA fetches it
  // once on boot, so a tab that was already open when the extension loaded —
  // or a cached reply — never shows it to us, and the row stays a bare id.
  // So scan EVERY /api2/v2/ reply for an account object whose id equals the
  // user-id we captured headers for. That id match is what keeps this honest:
  // these payloads are full of other people's accounts (fans, chat lists), and
  // only the one that IS us can ever set the label.
  // Flip to true in the console (window.__chatterlyDebug = true) to see why a
  // login is still showing a bare id.
  function dbg() {
    try {
      if (window.__chatterlyDebug) console.log("[Chatterly]", ...arguments);
    } catch (_) {}
  }

  function noteIdentity(url, text) {
    try {
      if (!text || lastIdent.username) return;          // already labelled
      const c = text.charAt(0);
      if (c !== "{" && c !== "[") return;
      if (text.indexOf('"username"') === -1) return;    // cheap reject
      const body = JSON.parse(text);

      // Preferred, header-independent path — the one that makes OF as reliable
      // as Fansly. /users/me (and the boot payload) return the signed-in user
      // as an account object flagged isAuth:true. That flag says "this is us"
      // without any header, so identity no longer waits on the user-id race
      // that left OF rows showing a bare id. It also backfills user-id so the
      // curl stays correct even if a signed request has not been seen yet.
      if (takeSelfMarked(body, 0)) {
        dbg("labelled from self-marker in", url);
        publish();
        return;
      }

      // Id-match path — for endpoints whose self object is NOT flagged (chat
      // lists, fan lists) but that still contain us somewhere. Needs to know
      // who we are first.
      const selfId = lastSeen["user-id"];
      if (!selfId) {
        // Body arrived before any signed request revealed who we are. Keep the
        // candidates; resolveIdentity() below settles them once user-id lands,
        // so an early payload is not lost for the rest of the session.
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

  // Find the account object OF marks as the signed-in user. isAuth is the
  // canonical self flag on /users/me; a couple of boot endpoints use the same
  // shape. Bounded recursion, first hit wins, and it must still carry a
  // username so we never label from a bare {isAuth:true} stub.
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

  // Accounts seen before we knew our own id: {id: {username, name}}.
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

  // Called once a signed request reveals user-id: if we already saw ourselves
  // in an earlier body, use it now.
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

  // Walk a decoded body looking for the account object that is us. OF nests
  // accounts differently per endpoint (bare, under .user, in a .list array),
  // so recurse rather than enumerate shapes — bounded in depth, and it stops
  // at the first id match.
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
    // Only emit when we have the bare minimum to build a curl.
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
            // Runtime-captured signing fields (may be partial if the page
            // hasn't called sign() yet — the popup will warn if missing).
            rules: {
              static_param: lastRules.static_param || null,
              start:        lastRules.start || null,
              end:          lastRules.end || null,
            },
            // Human label for the popup's saved-logins list (may be absent
            // until the page fetches /users/me — the id still works alone).
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

  // ── XHR ───────────────────────────────────────────────────────
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
      // Read the reply too — that is where the handle lives.
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

  // ── fetch() ───────────────────────────────────────────────────
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

  // ── Webpack module hooks (capture static_param + start + end) ──
  //
  // OF's signing pipeline (chunk 2313.js, exports.A):
  //   1. sha1(static_param + "\n" + time + "\n" + path + "\n" + userId)
  //   2. <obfuscated checksum derivation>
  //   3. return start + ":" + sha1Hex + ":" + abs(checksum).toString(16) + ":" + end
  //
  // We hook two webpack modules:
  //   • 89668 — js-sha1, to wrap the hash fn and read its 4-line input
  //   • 802313 — sign builder, to read start/end out of the returned sign
  //
  // Webpack stores chunks on `self.webpackChunkof_vue`; pushing into that
  // array is how OF loads modules. We override .push so every loaded
  // module passes through our wrappers.

  const wpChunks = (self.webpackChunkof_vue = self.webpackChunkof_vue || []);
  const origPush = wpChunks.push.bind(wpChunks);

  wpChunks.push = function (chunk) {
    const modules = chunk[1];
    if (!modules) return origPush(chunk);

    // js-sha1 — module 89668
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

    // Sign builder — module 802313 (exports.A is the sign function)
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
