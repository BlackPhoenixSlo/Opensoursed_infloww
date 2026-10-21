// ISOLATED-world bridge — receives the Fansly capture from the MAIN world and
// persists it to chrome.storage.local (which the MAIN world can't touch), then
// pings the service worker. Mirror of bridge.js for the OF side.

(function () {
  "use strict";

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.__fansly_capture !== true || !data.payload) return;

    const p = data.payload;
    if (!p.token || !p.accountId) return;   // not a usable session yet

    try {
      chrome.runtime.sendMessage({ type: "fanslyCapture", payload: p });
    } catch (_) {}

    // Merge so a header-only refresh never wipes an earlier fuller capture.
    chrome.storage.local.get(["lastFanslyCapture"]).then((cur) => {
      const prev = (cur && cur.lastFanslyCapture) || {};
      // Never carry one account's handle onto another's capture.
      const sameAcct = !prev.accountId
        || String(prev.accountId) === String(p.accountId || "");
      chrome.storage.local.set({
        lastFanslyCapture: {
          platform: "fansly",
          token: p.token || prev.token || null,
          id: p.id || prev.id || null,
          accountId: p.accountId || prev.accountId || null,
          username: p.username || (sameAcct ? prev.username : null) || null,
          displayName: p.displayName || (sameAcct ? prev.displayName : null) || null,
          device_id: p.device_id || prev.device_id || null,
          user_agent: p.user_agent || prev.user_agent || null,
          accept_language: p.accept_language || prev.accept_language || null,
          capturedAt: p.capturedAt || new Date().toISOString(),
          origin: location.origin,
        },
      });
    }).catch(() => {});
  });
})();
