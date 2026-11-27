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

export const CONTROL_WRITES = [
  "DELETE /admin/bio-pages/{pid}",
  "DELETE /admin/bio-pages/{pid}/avatar",
  "DELETE /admin/bio-pages/{pid}/background",
  "DELETE /admin/bio-pages/{pid}/domain",
  "DELETE /admin/bio-pages/{pid}/links/{lid}",
  "DELETE /admin/bio-pages/{pid}/links/{lid}/background",
  "DELETE /admin/chatters/invites/{token}",
  "DELETE /admin/employee-groups/{group_id}",
  "DELETE /admin/employees/{employee_id}",
  "DELETE /admin/funnels/{funnel_id}",
  "DELETE /admin/impersonate",
  "DELETE /admin/mcp",
  "DELETE /admin/owner-tokens/{token_id}",
  "DELETE /admin/shifts/clock-events/{clock_event_id}",
  "DELETE /admin/users/{user_id}",
  "DELETE /admin/users/{user_id}/accounts/{account_id}",
  "DELETE /admin/vault-ai/category-icons/{category}",
  "DELETE /push/subscription",
  "PATCH /admin/bio-pages/{pid}",
  "PATCH /admin/bio-pages/{pid}/links/{lid}",
  "PATCH /admin/employee-groups/{group_id}",
  "PATCH /admin/employees/{employee_id}",
  "PATCH /admin/shifts/clock-events/{clock_event_id}",
  "PATCH /admin/shifts/{shift_id}",
  "POST /admin/agency-notifications/dismiss-all",
  "POST /admin/agency-notifications/read-all",
  "POST /admin/agency-notifications/{notification_id}/dismiss",
  "POST /admin/agency-notifications/{notification_id}/read",
  "POST /admin/bio-pages",
  "POST /admin/bio-pages/{pid}/avatar",
  "POST /admin/bio-pages/{pid}/avatar/vault",
  "POST /admin/bio-pages/{pid}/background",
  "POST /admin/bio-pages/{pid}/background/vault",
  "POST /admin/bio-pages/{pid}/domain/check",
  "POST /admin/bio-pages/{pid}/links",
  "POST /admin/bio-pages/{pid}/links/{lid}/background",
  "POST /admin/bio-pages/{pid}/links/{lid}/background/vault",
  "POST /admin/chatters/invite",
  "POST /admin/chatters/invites/{token}/resend",
  "POST /admin/chatters/link",
  "POST /admin/employee-groups",
  "POST /admin/employees",
  "POST /admin/employees/login",
  "POST /admin/employees/{employee_id}/2fa/reset",
  "POST /admin/employees/{employee_id}/password",
  "POST /admin/funnels",
  "POST /admin/impersonate",
  "POST /admin/login/remote/queue",
  "POST /admin/mcp",
  "POST /admin/owner-tokens",
  "POST /admin/reports/files",
  "POST /admin/sensitive-words/add",
  "POST /admin/sensitive-words/delete",
  "POST /admin/sensitive-words/import",
  "POST /admin/sensitive-words/update",
  "POST /admin/shifts",
  "POST /admin/shifts/clock-heartbeat",
  "POST /admin/shifts/clock-in",
  "POST /admin/shifts/clock-out",
  "POST /admin/shifts/{shift_id}/cancel",
  "POST /admin/ultra/plans",
  "POST /admin/ultra/plans/{plan_id}/cancel",
  "POST /admin/ultra/plans/{plan_id}/ok",
  "POST /admin/ultra/plans/{plan_id}/pick",
  "POST /admin/users/{user_id}/accounts",
  "POST /admin/vault-ai/category-icons/{category}",
  "POST /api/cell/reservations/handoff",
  "POST /auth/2fa/activate",
  "POST /auth/2fa/disable",
  "POST /auth/2fa/init",
  "POST /auth/2fa/recovery-codes",
  "POST /auth/actor",
  "POST /auth/oauth/authorize",
  "POST /auth/oauth/register",
  "POST /auth/oauth/token",
  "POST /auth/register",
  "POST /auth/sessions/revoke-others",
  "POST /chatter/register",
  "POST /fleet/reservations",
  "POST /push/test",
  "PUT /admin/bio-pages/{pid}/domain",
  "PUT /admin/bio-pages/{pid}/links/order",
  "PUT /admin/chatters/{chatter_id}/account-access",
  "PUT /admin/chatters/{chatter_id}/folder-access",
  "PUT /admin/employee-groups/members",
  "PUT /admin/employees/{employee_id}/access",
  "PUT /admin/employees/{employee_id}/setup",
  "PUT /admin/mcp",
  "PUT /admin/my-llm-keys",
  "PUT /admin/ofm-writes/{account_id}",
  "PUT /admin/settings/{tab}",
  "PUT /admin/system/switches/{name}",
  "PUT /admin/users/{user_id}/llm-keys",
  "PUT /push/subscription"
] as const;

const controlWrites = CONTROL_WRITES.map((key) => {
  const [method, path] = key.split(" ");
  return { method, path: new RegExp(`^${path.replace(/\{[^}]+\}/g, "[^/]+")}$`) };
});

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

export function routeOf(url: string, headers: Headers, method = "GET"): Route {
  const u = new URL(url, "http://x");
  if (controlWrites.some((r) => r.method === method && r.path.test(u.pathname))) return "control";
  if (CONTROL_PATHS.some((p) => matches(u.pathname, p))) return "control";
  if (!relayBound(u.pathname)) return "app";
  if (accountOf(url, headers)) return "account";
  if (u.searchParams.get("cell") || headers.get("X-Cell-Id")) return "cell";
  return null;
}
