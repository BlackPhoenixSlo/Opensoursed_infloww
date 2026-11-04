/* eslint-disable */
/**
 * sw-push.js — Web Push for the app's one service worker. sw-images.js imports
 * it at its top (`try { importScripts("/sw-push.js"); } ...`, `// push sha256:`), so
 * both share the registration lib/registerImageSW.ts makes (prod builds only);
 * if this file throws, the image cache still installs and sw-images.js's own
 * fallback still shows every push (the brand + "New activity").
 *
 * VERSION DISCIPLINE: with EVERY change to this file, set the `// push sha256:`
 * line in sw-images.js to this file's sha256 (sw-push.test.ts fails until it
 * matches). That changes sw-images.js's bytes, which is the bump: an update
 * check byte-compares the main script and not every browser re-checks
 * imported ones, so a change without it may never reach an installed worker.
 *
 * push: the relay's payload `{v, tag, title, body, href, type, account_id,
 * icon}` (service/push_notice.py). Shown as an OS notification, ALWAYS when
 * unparseable (the brand + "New activity"): Apple revokes a subscription whose
 * pushes show nothing. One exception: off Apple, a window of the app that is
 * focused and visible is offered the notice (`push-notice`, with a reply
 * port) and toasts it through the same dedupe as its event stream
 * (toastStore.deliverPushNotice), which also covers a page whose stream idle
 * mode paused. It must answer `true` within ACK_MS; `false` (a Creator out of
 * its scope), no answer (no listener yet: a popout still booting, a page
 * mid-load) or a failed post shows it here after all. A notice with no Creator
 * (the relay's test) always shows.
 *
 * notificationclick: the app's focused or visible window (else its first) is
 * focused and told `open-notification` with the link (lib/webPush
 * listenNotificationClicks -> openNotification); with no window, the link opens one.
 *
 * The pure parts are on `self.__swPush` for app/public/sw-push.test.ts.
 */
(() => {
  const FALLBACK_BRAND = "Inflowwww";
  const ACK_MS = 1500; // a busy main thread acks late; past this the user gets both

  /** iOS / iPadOS, or Safari: a push must always show there. A worker's
   *  navigator may lack maxTouchPoints, so iPadOS's Mac UA is told by Safari's. */
  function isApple(nav) {
    const ua = (nav && nav.userAgent) || "";
    if (/iPhone|iPad|iPod/.test(ua)) return true;
    if (!/Macintosh/.test(ua)) return false;
    return (nav.maxTouchPoints || 0) > 1 ||
      (/Safari\//.test(ua) && !/Chrome|Chromium|Firefox|Edg|OPR/.test(ua));
  }

  function path(href) {
    return typeof href === "string" && href.startsWith("/") && !href.startsWith("//") ? href : "/";
  }

  /** `showNotification`'s arguments for a payload (null = unparseable). */
  function payloadToOptions(p, brand) {
    const str = (k) => (p && typeof p === "object" && typeof p[k] === "string" && p[k]) || undefined;
    const options = { body: str("body") || "New activity", data: { href: path(str("href")) } };
    if (str("tag")) options.tag = str("tag");
    if (str("icon")) options.icon = str("icon");
    return { title: str("title") || brand || FALLBACK_BRAND, options };
  }

  /** The window a click lands in: focused, else visible, else the first. */
  function pickClient(list) {
    if (!list || !list.length) return null;
    return list.find((c) => c.focused) || list.find((c) => c.visibilityState === "visible") || list[0];
  }

  /** The window that toasts a push instead of the OS, or null to show it. */
  function toastingClient(list, p, nav) {
    if (isApple(nav) || !p || typeof p !== "object" || !p.account_id) return null;
    return (list || []).find((c) => c.focused === true && c.visibilityState === "visible") || null;
  }

  /** Offers the notice to `page`: true once it answers that it toasted it. */
  function handedOff(page, p) {
    return new Promise((resolve) => {
      const ch = new MessageChannel();
      const done = (took) => { clearTimeout(timer); ch.port1.close(); resolve(took); };
      const timer = setTimeout(() => done(false), ACK_MS);
      ch.port1.onmessage = (e) => done(e.data === true);
      try { page.postMessage({ type: "push-notice", payload: p }, [ch.port2]); } catch (e) { done(false); }
    });
  }

  function parse(data) {
    try { return data ? data.json() : null; } catch (e) { return null; }
  }

  async function brandName() {
    try {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 2000);
      const m = await (await fetch("/manifest.webmanifest", { signal: ctl.signal })).json();
      clearTimeout(timer);
      return (typeof m.name === "string" && m.name) || FALLBACK_BRAND;
    } catch (e) {
      return FALLBACK_BRAND;
    }
  }

  const windows = () => self.clients.matchAll({ type: "window", includeUncontrolled: true });

  async function onPush(event) {
    const p = parse(event.data);
    const page = toastingClient(await windows(), p, self.navigator);
    if (page && await handedOff(page, p)) return;
    const { title, options } = payloadToOptions(p, p && p.title ? null : await brandName());
    await self.registration.showNotification(title, options);
  }

  async function onClick(event) {
    event.notification.close();
    const href = path(event.notification.data && event.notification.data.href);
    const c = pickClient(await windows());
    if (!c) return self.clients.openWindow(href);
    try { await c.focus(); } catch (e) { /* not allowed: still open it there */ }
    c.postMessage({ type: "open-notification", href });
  }

  self.addEventListener("push", (event) => {
    event.waitUntil(onPush(event).catch(() =>
      self.registration.showNotification(FALLBACK_BRAND, { body: "New activity", data: { href: "/" } })));
  });
  self.addEventListener("notificationclick", (event) => event.waitUntil(onClick(event)));

  self.__swPush = { payloadToOptions, pickClient, toastingClient, isApple, ACK_MS };
})();
