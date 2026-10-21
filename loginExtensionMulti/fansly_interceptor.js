// MAIN-world interceptor — runs at document_start on fansly.com.
//
// Fansly is far simpler than OnlyFans: there is no per-request signing to
// reverse. The whole reusable session is a localStorage blob plus the exact
// headers the client attaches. We capture BOTH:
//
//   1. The session blob (localStorage.session_active_session):
//        { token, id (=fansly-session-id), accountId, deviceId }
//      and the device id (localStorage.device_device_id).
//
//   2. Belt-and-suspenders: the live request headers on apiv3.fansly.com —
//        authorization, fansly-client-id, fansly-session-id, user-agent
//      so if Fansly ever moves the localStorage shape, the wire is ground
//      truth. (fansly-client-check is derived, not stored — the relay
//      recomputes it, so we don't need it.)
//
// Mirrors the OF interceptor's structure (MAIN captures + postMessage;
// ISOLATED bridge persists), so the two stay easy to keep in sync.

(function () {
  "use strict";

  const lastHdrs = {};   // authorization, fansly-client-id, fansly-session-id, user-agent
  const lastIdent = {};  // username, displayName — read off account responses

  function parseJsonBigIntSafe(raw) {
    // JSON.parse turns 18-19 digit snowflake ids into float64 numbers and
    // ROUNDS them (700174924320792578 -> 700174924320792600). Pre-quote any
    // 16+ digit integer VALUE so those ids survive as exact strings.
    const safe = String(raw).replace(/:(\s*)(-?\d{16,})(\s*[,}\]])/g, ':$1"$2"$3');
    return JSON.parse(safe);
  }

  function asIdStr(v) {
    // Never let an id leave here as a number — the backend types every id as a
    // string, and JSON round-trips of numbers past 2^53 lose precision.
    return (v === null || v === undefined) ? null : String(v);
  }

  function looksLikeSession(o) {
    // Fansly's session blob is a JSON object carrying at least a token and the
    // account id. The accountId lives ONLY here — no request header carries it
    // (the token's own first segment is the *session* id, not the account id),
    // so this blob is the single source of truth for who we are.
    return o && typeof o === "object"
      && typeof o.token === "string" && o.token
      && (o.accountId || o.account_id);
  }

  function readSession() {
    // localStorage is per-origin and shared with the page — readable here.
    try {
      let blob = null;

      // Fast path: the key Fansly uses today.
      const raw = localStorage.getItem("session_active_session");
      if (raw) {
        try { const o = parseJsonBigIntSafe(raw); if (looksLikeSession(o)) blob = o; } catch (_) {}
      }

      // Resilience: if Fansly ever renames that key, scan every localStorage
      // entry for the first value that parses to a session-shaped object. This
      // is what protects "will it capture the token" against a key rename — the
      // real failure mode, since the token can't be recovered from headers
      // without the accountId that only lives in this blob.
      if (!blob) {
        for (let i = 0; i < localStorage.length; i++) {
          const k = localStorage.key(i);
          const v = k && localStorage.getItem(k);
          if (!v || v.charAt(0) !== "{") continue;   // session blob is a JSON object
          try { const o = parseJsonBigIntSafe(v); if (looksLikeSession(o)) { blob = o; break; } } catch (_) {}
        }
      }

      if (!blob) return null;

      let deviceId = null;
      try {
        // Read as a RAW STRING — do NOT JSON.parse (that rounds the snowflake).
        const rawDev = localStorage.getItem("device_device_id");
        if (rawDev != null) deviceId = String(rawDev).trim().replace(/^"+|"+$/g, "") || null;
      } catch (_) {}
      return {
        token: blob.token || null,
        id: asIdStr(blob.id),                                  // fansly-session-id
        accountId: asIdStr(blob.accountId || blob.account_id), // us
        device_id: asIdStr(blob.deviceId || blob.device_id || deviceId),
      };
    } catch (_) {
      return null;
    }
  }

  // Pull our own handle out of any Fansly response that carries an account
  // object for us, so the popup can label a saved login "@handle" instead of
  // a bare 19-digit snowflake. Fansly wraps payloads as {success, response},
  // and `response` may be the account, a list of accounts, or {accounts:[...]}.
  function selfAccountId() {
    const sess = readSession();
    return (sess && sess.accountId) || null;
  }

  function noteIdentity(text, selfId) {
    try {
      if (!selfId || !text || text.charAt(0) !== "{") return;
      if (text.indexOf('"username"') === -1) return;   // cheap reject
      if (takeIdentity(parseJsonBigIntSafe(text), String(selfId), 0)) publish();
    } catch (_) {}
  }

  // Walk a decoded body for the account object that is US. Fansly nests
  // accounts differently per endpoint — response, response.account,
  // response.accounts, response.aggregationData.accounts — so recurse rather
  // than enumerate shapes, which quietly missed the messaging endpoints.
  // The id match is the safety rail: these payloads are mostly OTHER people
  // (fans, chat participants), and only the account that is us can label.
  function takeIdentity(node, selfId, depth) {
    if (!node || typeof node !== "object" || depth > 5) return false;
    if (Array.isArray(node)) {
      for (const item of node) if (takeIdentity(item, selfId, depth + 1)) return true;
      return false;
    }
    if (node.username && String(node.id) === selfId) {
      lastIdent.username = String(node.username);
      if (node.displayName) lastIdent.displayName = String(node.displayName);
      return true;
    }
    for (const k of Object.keys(node)) {
      const v = node[k];
      if (v && typeof v === "object" && takeIdentity(v, selfId, depth + 1)) return true;
    }
    return false;
  }

  function publish() {
    const sess = readSession();
    if (!sess || !sess.token) return;   // nothing worth publishing yet
    try {
      window.postMessage({
        __fansly_capture: true,
        payload: {
          platform: "fansly",
          token: sess.token,
          id: sess.id || lastHdrs["fansly-session-id"] || null,
          accountId: sess.accountId || null,
          device_id: sess.device_id || lastHdrs["fansly-client-id"] || null,
          username: lastIdent.username || null,
          displayName: lastIdent.displayName || null,
          user_agent: lastHdrs["user-agent"] || navigator.userAgent,
          accept_language: navigator.language || "en-US,en;q=0.9",
          capturedAt: new Date().toISOString(),
        },
      }, location.origin);
    } catch (_) {}
  }

  function recordHeader(name, value) {
    const lc = String(name || "").toLowerCase();
    if (!value) return;
    if (["authorization", "fansly-client-id", "fansly-session-id", "user-agent"].includes(lc)) {
      lastHdrs[lc] = String(value);
    }
  }

  // ── fetch() ───────────────────────────────────────────────────
  const _fetch = window.fetch;
  window.fetch = function (input, init) {
    try {
      const url = typeof input === "string" ? input : (input && input.url) || "";
      const hdrs = (init && init.headers) || (input && input.headers);
      if (hdrs) {
        if (typeof hdrs.forEach === "function") hdrs.forEach((v, k) => recordHeader(k, v));
        else if (Array.isArray(hdrs)) for (const [k, v] of hdrs) recordHeader(k, v);
        else for (const k of Object.keys(hdrs)) recordHeader(k, hdrs[k]);
      }
      if (url && url.includes("apiv3.fansly.com")) publish();
    } catch (_) {}
    const p = _fetch.apply(this, arguments);
    try {
      const u = typeof input === "string" ? input : (input && input.url) || "";
      if (u && u.includes("apiv3.fansly.com") && !lastIdent.username) {
        // .clone() so the app's own reader still sees an unconsumed body.
        return p.then((res) => {
          try {
            res.clone().text().then((t) => noteIdentity(t, selfAccountId())).catch(() => {});
          } catch (_) {}
          return res;
        });
      }
    } catch (_) {}
    return p;
  };

  // ── XHR ───────────────────────────────────────────────────────
  const _open = XMLHttpRequest.prototype.open;
  const _setHeader = XMLHttpRequest.prototype.setRequestHeader;
  const _send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, url, ...rest) {
    this.__f_url = typeof url === "string" ? url : "";
    return _open.call(this, m, url, ...rest);
  };
  XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
    recordHeader(name, value);
    return _setHeader.call(this, name, value);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    if (this.__f_url && this.__f_url.includes("apiv3.fansly.com")) {
      publish();
      try {
        this.addEventListener("load", () => {
          try {
            if (lastIdent.username) return;
            if (this.responseType === "" || this.responseType === "text") {
              noteIdentity(this.responseText, selfAccountId());
            }
          } catch (_) {}
        });
      } catch (_) {}
    }
    return _send.apply(this, args);
  };

  // The session is usually already in localStorage at load — publish once the
  // DOM is ready even if no XHR has fired yet.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", publish);
  } else {
    publish();
  }
  setTimeout(publish, 1500);
})();
