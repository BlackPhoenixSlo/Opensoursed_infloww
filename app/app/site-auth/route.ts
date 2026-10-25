/**
 * POST /site-auth: the public site's /login/ and /signup/ forms post here.
 *
 * The site is static and on another origin, and nothing in app/ or service/
 * speaks CORS, so the forms do a plain top-level urlencoded POST (no CORS
 * needed). This handler turns it into the relay's JSON /auth/sign-in (owners
 * then employees, one password check, as the app's own /login) or
 * /auth/register, copies the relay's Set-Cookie onto a 303:
 *   success -> the Dashboard (/) on this app, already signed in, with
 *     Clear-Site-Data "storage" so no previous identity's cached data paints
 *     first. The app's own login runs wipeIdentityCaches (UserContext.tsx)
 *     for the same reason; this is broader: it also resets the UI preferences
 *     that wipe keeps (theme, chat sort, emoji recents, ...). The HTTP cache
 *     is left alone, as the app's wipe leaves it.
 *   2FA on (or required by the employee's Agency) -> the app's /login with the
 *     username filled in: the code step lives there, and the sign-in ticket
 *     never goes in a URL.
 *   failure -> back to the site page with #error=<code>&username=<name>. The
 *     fragment never reaches the site's host, so its logs never see the
 *     username. The site owns the wording of each code.
 * The password is never put in a URL and never logged.
 *
 * The session cookie is SameSite=Lax. Setting it on the response to a
 * cross-site top-level POST is allowed, and the 303 makes the next request a
 * top-level GET, which carries Lax cookies, so / opens signed in. Not
 * /messages-pro: that is a window of its own (ADR-0002), not the main page.
 *
 * Kept out of /auth/* on purpose: that prefix is rewritten to the relay
 * (next.config.ts), and a deployment that routes it straight to the relay
 * would never reach this file.
 *
 * Only the configured site may post here (Origin check), so another site
 * cannot sign a visitor into an account it picked. The check is by origin, so
 * the WHOLE site origin is trusted: for the default that is every page on
 * https://inflowwww.com. The site pages send their origin because
 * they set `<meta name="referrer" content="origin-when-cross-origin">`: under
 * the default strict-origin-when-cross-origin an https page posting to http
 * (http://localhost included) sends `Origin: null`, which is refused here.
 *
 * Redirect targets are fixed here, never read from the request. SITE_URL
 * (env, read once at start) overrides the default site, e.g. for a local
 * preview of web/; a malformed value falls back to the default (lib/site.ts,
 * which NEXT_PUBLIC_SITE_URL sets at build time for the app's own site links).
 *
 * Fleet (.scratch/fleet-sharding/DESIGN.md §3, §10.2): many shards, each its
 * own app + relay at https://sNN.<domain>, one of them the front at
 * https://login.<domain> where the site's forms post. With FLEET_PEERS set
 * (the front only) a post first asks every relay, its own and each peer's,
 * whether the username exists (GET /auth/fleet/whois, service/fleet_api.py;
 * the name in a header, the password never). One hit here is today's path;
 * one hit on a peer is a 200 page that re-posts the form from the visitor's
 * browser to that shard's /site-auth, so the password goes only to the shard
 * that holds the login and that shard's throttle sees the visitor's own IP;
 * none is `wrong`, two or more is `workspace` (fail closed). A signup refuses
 * a name any shard holds and is re-posted to FLEET_OPEN when that is another
 * shard. Every shard accepts posts from FLEET_FRONT_ORIGIN as well as the
 * site. Lookups cost a token from a per-client-IP bucket on the front.
 */

import { createHash } from "node:crypto";

import { SITE_URL } from "@/lib/site";

const RELAY_URL = process.env.RELAY_URL || "http://127.0.0.1:8787";

function parseSite(raw: string | undefined): URL {
  try {
    const url = new URL(raw || SITE_URL);
    if (url.protocol === "https:" || url.protocol === "http:") return url;
  } catch {
    /* fall through to the default */
  }
  return new URL(SITE_URL);
}

const SITE = parseSite(process.env.SITE_URL);
const SITE_BASE = SITE.href.replace(/\/+$/, "");

/** An http(s) URL's origin, or null for anything else. */
function httpOrigin(raw: string | undefined): string | null {
  try {
    const url = new URL(String(raw ?? "").trim());
    if (url.protocol === "https:" || url.protocol === "http:") return url.origin;
  } catch {
    /* not a URL */
  }
  return null;
}

type Peer = { origin: string; base: string };

/** FLEET_PEERS: `<public origin>` or `<public origin>|<whois base URL>`, comma-separated. */
function parsePeers(raw: string | undefined): Peer[] {
  const peers: Peer[] = [];
  for (const entry of (raw ?? "").split(",").map((e) => e.trim()).filter(Boolean)) {
    const [pub, via, ...rest] = entry.split("|");
    const origin = httpOrigin(pub);
    const base = via === undefined ? origin : httpOrigin(via) && via.trim().replace(/\/+$/, "");
    if (origin && base && rest.length === 0) peers.push({ origin, base });
    else console.error(`site-auth: FLEET_PEERS entry dropped, not <origin> or <origin>|<url>: ${entry}`);
  }
  return peers;
}

const FLEET_SECRET = process.env.FLEET_SECRET ?? "";
const FRONT = httpOrigin(process.env.FLEET_FRONT_ORIGIN);
const PEERS = parsePeers(process.env.FLEET_PEERS);
const OPEN = httpOrigin(process.env.FLEET_OPEN);
if (PEERS.length && FLEET_SECRET.length < 32) console.error("site-auth: FLEET_PEERS set but FLEET_SECRET < 32 chars; every lookup will fail");

type SiteAuthError =
  | "taken" | "reserved" | "invalid" | "wrong" | "disabled" | "unavailable" | "throttled" | "workspace";

function redirect(location: string, extra: [string, string][] = []): Response {
  const headers = new Headers({ Location: location, "Cache-Control": "no-store" });
  for (const [k, v] of extra) headers.append(k, v);
  return new Response(null, { status: 303, headers });
}

/** POST JSON to the relay. Throws when the relay cannot be reached. The
 *  sign-in throttle keys on the client's address (service/login_throttle.py),
 *  so the X-Forwarded-For this request came with goes on unchanged. */
function relay(req: Request, path: string, username: string, password: string): Promise<Response> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const forwarded = req.headers.get("x-forwarded-for");
  if (forwarded) headers["X-Forwarded-For"] = forwarded;
  return fetch(`${RELAY_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify({ username, password }),
    cache: "no-store",
    redirect: "manual",
    signal: AbortSignal.timeout(15_000),
  });
}

async function registerError(res: Response): Promise<SiteAuthError> {
  if (res.status === 409) return "taken";
  if (res.status === 429) return "throttled";
  if (res.status === 400) {
    const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
    return typeof body.detail === "string" && /reserved/i.test(body.detail) ? "reserved" : "invalid";
  }
  if (res.status === 422) return "invalid";
  return "unavailable";
}

// ── Fleet front: the lookup limit, whois and the hand-off page ─────────

const LOOKUP_CAPACITY = 30;
const LOOKUP_REFILL_MS = 2_000;
const LOOKUP_MAX_KEYS = 10_000;
const lookups = new Map<string, { tokens: number; at: number }>();

/** One lookup token for this client, keyed on the last X-Forwarded-For entry
 *  (Caddy's; the app port is loopback-only). False when the bucket is empty. */
function takeLookup(req: Request): boolean {
  const key = (req.headers.get("x-forwarded-for") ?? "").split(",").pop()!.trim();
  const now = Date.now();
  const prev = lookups.get(key);
  const tokens = prev
    ? Math.min(LOOKUP_CAPACITY, prev.tokens + (now - prev.at) / LOOKUP_REFILL_MS)
    : LOOKUP_CAPACITY;
  lookups.delete(key); // re-inserted last, so the first key is the stalest
  if (lookups.size >= LOOKUP_MAX_KEYS) lookups.delete(lookups.keys().next().value!);
  lookups.set(key, { tokens: tokens >= 1 ? tokens - 1 : tokens, at: now });
  return tokens >= 1;
}

/** Does the relay at `base` hold this username? null when it did not answer. */
async function whois(base: string, username: string): Promise<boolean | null> {
  try {
    const res = await fetch(`${base}/auth/fleet/whois`, {
      headers: { "X-Fleet-Secret": FLEET_SECRET, "X-Fleet-Username": encodeURIComponent(username) },
      signal: AbortSignal.timeout(3_000),
      cache: "no-store",
    });
    if (res.status !== 200) return null;
    const body = (await res.json()) as { exists?: unknown };
    return typeof body.exists === "boolean" ? body.exists : null;
  } catch {
    return null;
  }
}

const HANDOFF_SCRIPT = "document.forms[0].submit()";
const HANDOFF_HASH = createHash("sha256").update(HANDOFF_SCRIPT).digest("base64");

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

/** The page that re-posts the form from the visitor's browser to `target`'s
 *  /site-auth. `target` is always an origin from env, never from the request.
 *  The form may also land on the site: the target's failures 303 there. */
function handoff(target: string, fields: Record<string, string>): Response {
  const inputs = Object.entries(fields)
    .map(([k, v]) => `<input type="hidden" name="${k}" value="${escapeHtml(v)}">`)
    .join("");
  const html =
    `<!doctype html><html><head><meta charset="utf-8"><title>Signing in</title></head><body>` +
    `<form method="post" action="${escapeHtml(target)}/site-auth">${inputs}` +
    `<noscript><button type="submit">Continue</button></noscript></form>` +
    `<script>${HANDOFF_SCRIPT}</script></body></html>`;
  return new Response(html, {
    status: 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      // Not no-referrer: that would send the next post as Origin: null.
      "Referrer-Policy": "origin-when-cross-origin",
      "Content-Security-Policy":
        `default-src 'none'; script-src 'sha256-${HANDOFF_HASH}'; ` +
        `form-action ${target} ${SITE.origin}; frame-ancestors 'none'`,
    },
  });
}

export async function POST(req: Request): Promise<Response> {
  const origin = req.headers.get("origin");
  if (origin !== SITE.origin && !(FRONT && origin === FRONT)) {
    return new Response("Forbidden: this form only accepts posts from the Inflowwww site.", {
      status: 403,
      headers: { "Cache-Control": "no-store" },
    });
  }

  const form = await req.formData().catch(() => null);
  const register = form?.get("mode") === "register";
  const username = String(form?.get("username") ?? "").trim().toLowerCase();
  const password = String(form?.get("password") ?? "");

  const fail = (error: SiteAuthError) => {
    const q = new URLSearchParams({ error });
    if (username) q.set("username", username);
    return redirect(`${SITE_BASE}/${register ? "signup" : "login"}/#${q}`);
  };
  if (!username || !password) return fail("invalid");

  if (PEERS.length) {
    if (!takeLookup(req)) return fail("throttled");
    const found = await Promise.all([whois(RELAY_URL, username), ...PEERS.map((p) => whois(p.base, username))]);
    const hits = found.flatMap((hit, i) => (hit ? [i === 0 ? null : PEERS[i - 1].origin] : []));
    if (register) {
      if (hits.length) return fail("taken");
      if (found.includes(null)) return fail("unavailable");
      if (OPEN && OPEN !== FRONT) return handoff(OPEN, { username, password, mode: "register" });
    } else {
      if (hits.length > 1) return fail("workspace");
      if (!hits.length) return fail(found.includes(null) ? "unavailable" : "wrong");
      if (hits[0]) return handoff(hits[0], { username, password, mode: "login" });
    }
  }

  let res: Response;
  try {
    if (register) {
      res = await relay(req, "/auth/register", username, password);
      if (!res.ok) return fail(await registerError(res));
    } else {
      res = await relay(req, "/auth/sign-in", username, password);
      if (res.status === 401) return fail("wrong");
      if (res.status === 403) return fail("disabled");
      if (res.status === 429) return fail("throttled");
      if (res.status === 400 || res.status === 422) return fail("invalid");
      if (!res.ok) return fail("unavailable");
      const body = (await res.clone().json().catch(() => null)) as { two_factor?: unknown } | null;
      if (body && body.two_factor) return redirect(`/login?${new URLSearchParams({ username })}`);
    }
  } catch {
    return fail("unavailable");
  }
  return redirect("/", [
    ...res.headers.getSetCookie().map((c): [string, string] => ["Set-Cookie", c]),
    ["Clear-Site-Data", '"storage"'],
  ]);
}
