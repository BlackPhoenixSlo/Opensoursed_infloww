(function () {
  "use strict";

  const lastHdrs = {};
  const lastIdent = {};

  // JSON.parse rounds 18-19 digit snowflake ids; pre-quote 16+ digit values so they stay exact.
  function parseJsonBigIntSafe(raw) {
    const safe = String(raw).replace(/:(\s*)(-?\d{16,})(\s*[,}\]])/g, ':$1"$2"$3');
    return JSON.parse(safe);
  }

  function asIdStr(v) {
    return (v === null || v === undefined) ? null : String(v);
  }

  function looksLikeSession(o) {
    return o && typeof o === "object"
      && typeof o.token === "string" && o.token
      && (o.accountId || o.account_id);
  }

  function readSession() {
    try {
      let blob = null;

      const raw = localStorage.getItem("session_active_session");
      if (raw) {
        try { const o = parseJsonBigIntSafe(raw); if (looksLikeSession(o)) blob = o; } catch (_) {}
      }

      if (!blob) {
        // Scan every key in case Fansly renames the session key: accountId lives only in this blob.
        for (let i = 0; i < localStorage.length; i++) {
          const k = localStorage.key(i);
          const v = k && localStorage.getItem(k);
          if (!v || v.charAt(0) !== "{") continue;
          try { const o = parseJsonBigIntSafe(v); if (looksLikeSession(o)) { blob = o; break; } } catch (_) {}
        }
      }

      if (!blob) return null;

      let deviceId = null;
      try {
        const rawDev = localStorage.getItem("device_device_id");
        if (rawDev != null) deviceId = String(rawDev).trim().replace(/^"+|"+$/g, "") || null;
      } catch (_) {}
      return {
        token: blob.token || null,
        id: asIdStr(blob.id),
        // No request header carries the accountId; the token's first segment is the session id.
        accountId: asIdStr(blob.accountId || blob.account_id),
        device_id: asIdStr(blob.deviceId || blob.device_id || deviceId),
      };
    } catch (_) {
      return null;
    }
  }

  function selfAccountId() {
    const sess = readSession();
    return (sess && sess.accountId) || null;
  }

  function noteIdentity(text, selfId) {
    try {
      if (!selfId || !text || text.charAt(0) !== "{") return;
      if (text.indexOf('"username"') === -1) return;
      if (takeIdentity(parseJsonBigIntSafe(text), String(selfId), 0)) publish();
    } catch (_) {}
  }

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
    if (!sess || !sess.token) return;
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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", publish);
  } else {
    publish();
  }
  setTimeout(publish, 1500);
})();
