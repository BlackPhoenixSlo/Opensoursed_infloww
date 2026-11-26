// Must equal the Front door in deploy/fleet/fleet.py; cellRoute.test.ts fails on drift.
export const CONTROL_PATHS = [
  "/auth/*", "/chatter/*", "/livez", "/fleet/*", "/admin/chatters", "/admin/chatters/*",
  "/admin/employees", "/admin/employees/*", "/admin/employee-groups", "/admin/employee-groups/*",
  "/admin/notifications", "/admin/notifications/*", "/admin/shifts", "/admin/shifts/*",
  "/admin/clock", "/admin/clock/*", "/admin/impersonate",
] as const;
export const RELAY_PATHS = ["/api/of/*", "/img", "/img/*", "/events", "/auth/*", "/chatter/*", "/livez"] as const;
export const ACCOUNT_PATH_RES = [
  String.raw`^/admin/(?:accounts|copilot|fans|messages|of-consent|ofm-writes|roster`
    + String.raw`|funnels/[^/]+/media|s4s/profiles)/([0-9]+)(?:/|$)`,
  String.raw`^/admin/ingest/transactions/([0-9]+)/(?:pause|resume|run)(?:/|$)`,
] as const;

const ACCOUNT_RES = ACCOUNT_PATH_RES.map((r) => new RegExp(r));

function matches(path: string, pattern: string): boolean {
  return pattern.endsWith("/*") ? path.startsWith(pattern.slice(0, -1)) : path === pattern;
}

const relayBound = (path: string) =>
  RELAY_PATHS.some((p) => matches(path, p)) || (path.startsWith("/admin/") && path !== "/admin/manage");

export function accountOf(url: string, headers: Headers): string | null {
  const u = new URL(url, "http://x");
  let account: string | null = null;
  for (const re of ACCOUNT_RES) account = re.exec(u.pathname)?.[1] ?? account;
  for (const v of [u.searchParams.get("account"), u.searchParams.get("account_id"), headers.get("X-Account-Id")]) {
    if (v) account = v;
  }
  return account;
}

export type Route = "app" | "control" | "account" | "cell" | null;

export function routeOf(url: string, headers: Headers): Route {
  const u = new URL(url, "http://x");
  if (CONTROL_PATHS.some((p) => matches(u.pathname, p))) return "control";
  if (!relayBound(u.pathname)) return "app";
  if (accountOf(url, headers)) return "account";
  if (u.searchParams.get("cell") || headers.get("X-Cell-Id")) return "cell";
  return null;
}
