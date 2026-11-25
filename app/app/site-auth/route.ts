import { createHash } from "node:crypto";

import { SITE_URL } from "@/lib/site";
import { BRAND_NAME } from "@/lib/brand";

const RELAY_URL = process.env.RELAY_URL || "http://127.0.0.1:8787";

function parseSite(raw: string | undefined): URL {
  try {
    const url = new URL(raw || SITE_URL);
    if (url.protocol === "https:" || url.protocol === "http:") return url;
  } catch {
  }
  return new URL(SITE_URL);
}

const SITE = parseSite(process.env.SITE_URL);
const SITE_BASE = SITE.href.replace(/\/+$/, "");

function httpOrigin(raw: string | undefined): string | null {
  try {
    const url = new URL(String(raw ?? "").trim());
    if (url.protocol === "https:" || url.protocol === "http:") return url.origin;
  } catch {
  }
  return null;
}

type Peer = { origin: string; base: string };

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

function relay(req: Request, path: string, username: string, password: string): Promise<Response> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  // The sign-in throttle keys on the client address: pass X-Forwarded-For through unchanged.
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


const LOOKUP_CAPACITY = 30;
const LOOKUP_REFILL_MS = 2_000;
const LOOKUP_MAX_KEYS = 10_000;
const lookups = new Map<string, { tokens: number; at: number }>();

function takeLookup(req: Request): boolean {
  // Last X-Forwarded-For entry is Caddy's; the app port is loopback-only.
  const key = (req.headers.get("x-forwarded-for") ?? "").split(",").pop()!.trim();
  const now = Date.now();
  const prev = lookups.get(key);
  const tokens = prev
    ? Math.min(LOOKUP_CAPACITY, prev.tokens + (now - prev.at) / LOOKUP_REFILL_MS)
    : LOOKUP_CAPACITY;
  lookups.delete(key);
  if (lookups.size >= LOOKUP_MAX_KEYS) lookups.delete(lookups.keys().next().value!);
  lookups.set(key, { tokens: tokens >= 1 ? tokens - 1 : tokens, at: now });
  return tokens >= 1;
}

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

// Not under /auth/*: the edge routes that prefix directly to the relay.
export async function POST(req: Request): Promise<Response> {
  // Origin check trusts the whole site origin; only the configured site may sign a visitor in.
  const origin = req.headers.get("origin");
  if (origin !== SITE.origin && !(FRONT && origin === FRONT)) {
    return new Response(`Forbidden: this form only accepts posts from the ${BRAND_NAME} site.`, {
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
