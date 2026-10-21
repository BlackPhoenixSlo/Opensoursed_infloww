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
 */

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

type SiteAuthError = "taken" | "reserved" | "invalid" | "wrong" | "disabled" | "unavailable";

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
  if (res.status === 400) {
    const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
    return typeof body.detail === "string" && /reserved/i.test(body.detail) ? "reserved" : "invalid";
  }
  if (res.status === 422) return "invalid";
  return "unavailable";
}

export async function POST(req: Request): Promise<Response> {
  if (req.headers.get("origin") !== SITE.origin) {
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

  let res: Response;
  try {
    if (register) {
      res = await relay(req, "/auth/register", username, password);
      if (!res.ok) return fail(await registerError(res));
    } else {
      res = await relay(req, "/auth/sign-in", username, password);
      if (res.status === 401) return fail("wrong");
      if (res.status === 403) return fail("disabled");
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
