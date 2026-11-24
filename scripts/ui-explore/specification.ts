// UI exploration spec (Bombadil 0.8.0). Every exported formula is a property, every exported
// generator an action source. Run via scripts/ui-explore/run.sh; README.md has the rules.
import { always } from "@antithesishq/bombadil";
import { isAction } from "@antithesishq/bombadil/actions";
import { type Fingerprint, actions, extract, registerCustomAction, weighted } from "@antithesishq/bombadil/browser";
import {
  clicks,
  inputs,
  navigation,
  scroll,
  waitOnce,
} from "@antithesishq/bombadil/browser/defaults/actions";

// Built-ins: uncaught exceptions, unhandled rejections, document responses < 400.
// (Their noConsoleErrors is replaced below by one with an allowlist.)
export {
  noHttpErrorCodes,
  noUncaughtExceptions,
  noUnhandledPromiseRejections,
} from "@antithesishq/bombadil/browser/defaults/properties";

// console.error allowlist. Rule: one regex per entry, matched against the first line of the
// message, each with the reason it is not a product bug. Never add a real bug here.
const CONSOLE_ALLOW: [RegExp, string][] = [];

// Off-host request allowlist, same rule. Chrome resolves no name but loopback (run.sh), so these
// were attempted but never left the machine.
const OFFHOST_ALLOW: [RegExp, string][] = [
  [/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, "app/public/download.html links Google Fonts by design; capture.py stubs the same hosts"],
];

const LOOPBACK = ["127.0.0.1", "localhost", "[::1]"];
const PHONE_WIDTH = 390;

const consoleErrors = extract((state) => {
  const out: string[] = [];
  for (const e of state.console) {
    if (e.level !== "error") continue;
    out.push(e.args.map((a) => (typeof a === "string" ? a.split("\n")[0] : JSON.stringify(a))).join(" "));
  }
  return out;
});

export const noConsoleErrors = always(() =>
  consoleErrors.current.every((m) => CONSOLE_ALLOW.some(([re]) => re.test(m))),
);

// Every request the page made (fetch, XHR, images, scripts) since it loaded: any 5xx from the
// relay (through next dev's rewrites) or next itself, and any that left loopback.
const requests = extract((state) => {
  const perf = state.window.performance;
  // Default buffer is 250 entries; a long-lived SPA page would stop recording.
  if (!(state.window as unknown as { __uiExploreBuf?: boolean }).__uiExploreBuf) {
    perf.setResourceTimingBufferSize(1_000_000);
    (state.window as unknown as { __uiExploreBuf?: boolean }).__uiExploreBuf = true;
  }
  const server5xx: string[] = [];
  const offHost: string[] = [];
  for (const e of perf.getEntriesByType("resource") as PerformanceResourceTiming[]) {
    let host = "";
    try {
      const u = new URL(e.name);
      if (u.protocol === "data:" || u.protocol === "blob:") continue;
      host = u.hostname;
    } catch {
      continue;
    }
    if (!LOOPBACK.includes(host)) {
      if (!OFFHOST_ALLOW.some(([re]) => re.test(e.name))) offHost.push(e.name.slice(0, 200));
    }
    else if ((e.responseStatus ?? 0) >= 500) server5xx.push(`${e.responseStatus} ${e.name.slice(0, 200)}`);
  }
  return { server5xx, offHost };
});

export const noRelay5xx = always(() => requests.current.server5xx.length === 0);

// Parsed in the page: the spec runtime has no URL.
const page = extract((state) => {
  try {
    const { protocol, hostname, pathname, origin } = new URL(state.navigationHistory.current.url);
    return { protocol, hostname, pathname, origin };
  } catch {
    return { protocol: "", hostname: "", pathname: "", origin: "" };
  }
});

// about:blank is Bombadil's start page; an in-app history.back() can land there (see `recover`).
export const staysOnLoopback = always(() => {
  const { protocol, hostname } = page.current;
  return (protocol === "about:" || LOOPBACK.includes(hostname)) && requests.current.offHost.length === 0;
});

// Next's dev overlay (error dialog or the issues badge with a count) and the app's own crash screens:
// components/ErrorBoundary.tsx, app/global-error.tsx (replaces the whole page), Next's client crash page.
const crashScreen = extract((state) => {
  const shadow = state.document.querySelector("nextjs-portal")?.shadowRoot;
  const issues = shadow?.querySelector("[data-issues-count]")?.textContent?.trim() ?? "";
  if (shadow?.querySelector("[data-nextjs-dialog]")) return "next dev error overlay open";
  if (issues && issues !== "0") return `next dev issues badge: ${issues}`;
  const text = state.document.body?.innerText ?? "";
  if (text.includes("Something broke.") && text.includes("/admin/errors")) return "ErrorBoundary: Something broke.";
  if (/^\s*Something went wrong\.\s*(Retry|Try again)?\s*$/.test(text)) return "global-error page";
  if (text.includes("Application error: a client-side exception has occurred")) return "Next client crash page";
  return null;
});

export const noErrorScreen = always(() => crashScreen.current === null);

// Broken values on screen: innerText is the rendered, visible text only.
const badText = extract((state) => {
  const text = state.document.body?.innerText ?? "";
  const hits: string[] = [];
  for (const re of [/\$\s?NaN/, /\bNaN\b/, /\bundefined\b/, /\[object Object\]/]) {
    const m = re.exec(text);
    if (m) hits.push(JSON.stringify(text.slice(Math.max(0, m.index - 40), m.index + 40)));
  }
  return hits;
});

export const noBrokenValues = always(() => badText.current.length === 0);

// At phone width the page must not scroll sideways. Reports the widest overflowing element.
const overflow = extract((state) => {
  const w = state.window.innerWidth;
  if (w > PHONE_WIDTH) return null;
  const sw = state.document.documentElement.scrollWidth;
  if (sw <= w + 1) return null;
  let worst = "";
  let right = w;
  for (const el of Array.from(state.document.body?.querySelectorAll("*") ?? [])) {
    const r = el.getBoundingClientRect();
    if (r.right > right + 1 && r.width > 0) {
      right = r.right;
      worst = `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}.${String(el.className).slice(0, 80)}`;
    }
  }
  return { viewport: w, scrollWidth: sw, widest: worst };
});

export const noHorizontalOverflowPhone = always(() => overflow.current === null);

// ── Actions ──────────────────────────────────────────────────────────────────
// Signed out (any reason) -> sign back in as the seeded owner (seed_session.py), so the run keeps
// exploring the app instead of the login page. The sign-out controls themselves are never clicked.
function onLogin(): boolean {
  return /^\/(login|chatter-login)\/?$/.test(page.current.pathname);
}

// An app "Back" button (history.back()) past the first entry leaves the app for about:blank,
// where Bombadil has no actions: return to the app origin seen last.
let appOrigin = "";
function offApp(): boolean {
  const inApp = LOOPBACK.includes(page.current.hostname);
  if (inApp) appOrigin = page.current.origin;
  return !inApp;
}

const home = registerCustomAction("home", async (_document, window, origin: string) => {
  window.location.assign(`${origin}/`);
});

const reauth = registerCustomAction("reauth", async (_document, window) => {
  const response = await window.fetch("/__ui-explore/reauth", {
    method: "POST",
    headers: { "content-type": "application/json" },
    redirect: "error",
    credentials: "same-origin",
  });
  if (!response.ok) throw new Error(`Seeded owner login failed (HTTP ${response.status})`);
  window.location.assign("/");
});

const SIGN_OUT = /\b(sign|log)\s?out\b(?! (of this account on every other|other sessions))/i;

function isSignOut(f: Fingerprint): boolean {
  return [f.accessibleName, f.textContent].some((s) => s !== null && SIGN_OUT.test(s));
}

// Next's dev tools (badge, menu: "Route Info", "Restart Dev Server", ...) are not the product.
const devTools = extract((state) => {
  const shadow = state.document.querySelector("nextjs-portal")?.shadowRoot;
  if (!shadow) return [];
  return Array.from(shadow.querySelectorAll("a, button, input, [role]"))
    .map((el) => el.getBoundingClientRect())
    .filter((r) => r.width > 0 && r.height > 0)
    .map(({ left, top, right, bottom }) => ({ left, top, right, bottom }));
});

function inDevTools(x: unknown, y: unknown): boolean {
  return typeof x === "number" && typeof y === "number" &&
    devTools.current.some((r) => x >= r.left && x <= r.right && y >= r.top && y <= r.bottom);
}

const appClicks = clicks.filter((a) => !(isAction(a, "Click") &&
  (isSignOut(a.Click.fingerprint) || inDevTools(a.Click.point.x, a.Click.point.y))));

export const explore = weighted([
  [100, appClicks],
  [100, inputs],
  [50, scroll],
  [10, navigation],
  [1, waitOnce],
]).when(() => !offApp() && !onLogin());

export const recover = actions(() => {
  if (offApp()) return appOrigin ? [home(appOrigin)] : [];
  return onLogin() ? [reauth()] : [];
});
