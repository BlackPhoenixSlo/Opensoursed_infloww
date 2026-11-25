(function () {
  "use strict";

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.__chatterly_capture !== true || !data.payload) return;

    const payload = data.payload;
    if (!payload.headers || !payload.headers["x-of-rev"] || !payload.headers["user-id"]) return;

    try {
      chrome.runtime.sendMessage({
        type: "capture",
        payload: payload,
      });
    } catch (_) {
      // Service worker may be asleep: the storage write below is the real source of truth.
    }

    chrome.storage.local.get(["lastCapture"]).then((cur) => {
      const prev = (cur && cur.lastCapture) || {};
      const prevRules = prev.rules || {};
      const newRules = payload.rules || {};
      // Merge with the stored rules: a header-only publish must not wipe a captured static_param (rules trickle in across postMessages).
      const mergedRules = {
        static_param: newRules.static_param || prevRules.static_param || null,
        start:        newRules.start        || prevRules.start        || null,
        end:          newRules.end          || prevRules.end          || null,
      };
      // The handle arrives on a later publish than the headers (needs a /users/me reply); drop a stale one if the capture is for another user-id.
      const sameUser = !prev.headers
        || String(prev.headers["user-id"] || "") === String(payload.headers["user-id"] || "");
      chrome.storage.local.set({
        lastCapture: {
          headers: payload.headers,
          rules: mergedRules,
          username: payload.username || (sameUser ? prev.username : null) || null,
          displayName: payload.displayName || (sameUser ? prev.displayName : null) || null,
          url: payload.url,
          capturedAt: payload.capturedAt,
          origin: location.origin,
        },
      });
    }).catch(() => {});
  });
})();
