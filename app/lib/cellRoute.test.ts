import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { ACCOUNT_PATH_RES, CONTROL_PATHS, CONTROL_WRITES, RELAY_PATHS, accountOf, routeOf } from "@/lib/cellRoute";

const FLEET = readFileSync(resolve(__dirname, "../../deploy/fleet/fleet.py"), "utf8");

function pyTuple(name: string): string[] {
  const body = new RegExp(`^${name} = \\(([\\s\\S]*?)\\)\\n`, "m").exec(FLEET)?.[1];
  if (!body) throw new Error(`${name} not found in fleet.py`);
  return [...body.matchAll(/"([^"]*)"/g)].map((m) => m[1]);
}

describe("mirror of the Front door in fleet.py", () => {
  it("control and relay paths match", () => {
    expect([...CONTROL_PATHS]).toEqual(pyTuple("CONTROL_PATHS"));
    expect([...RELAY_PATHS]).toEqual(pyTuple("RELAY_PATHS"));
  });
  it("matches fleet control writes by method and path", () => {
    const { routes } = JSON.parse(readFileSync(resolve(__dirname, "../../service/cell_scope.json"), "utf8"));
    expect([...CONTROL_WRITES]).toEqual(Object.keys(routes).filter((key) =>
      routes[key].scope === "agency" && !/^(GET|HEAD|OPTIONS) /.test(key)));
    expect(routeOf("/admin/users/42/accounts", h(), "POST")).toBe("control");
    expect(routeOf("/admin/users/42/accounts", h(), "GET")).toBeNull();
    expect(routeOf("/admin/my-llm-keys", h(), "PUT")).toBe("control");
  });
  it("account path regexes match", () => {
    const body = /^ACCOUNT_PATH_RES = \(([\s\S]*?)\n\)\n/m.exec(FLEET)?.[1] ?? "";
    const res = [...body.matchAll(/\("acct_\w+", ((?:\s*r"[^"]*")+)\)/g)]
      .map((m) => [...m[1].matchAll(/r"([^"]*)"/g)].map((x) => x[1]).join(""));
    expect(res).toEqual([...ACCOUNT_PATH_RES]);
  });
});

const h = (o: Record<string, string> = {}) => new Headers(o);

describe("routeOf", () => {
  it.each([
    ["/auth/me", {}, "control"],
    ["/admin/shifts/7/cancel", {}, "control"],
    ["/admin/chatters", {}, "control"],
    ["/admin/agency-notifications?limit=30", {}, "control"],
    ["/admin/agency-notifications/read-all", {}, "control"],
    ["/admin/agency-notifications/17/dismiss", {}, "control"],
    ["/admin/notifications", {}, null],
    ["/api/assistant", {}, "app"],
    ["/admin/manage", {}, "app"],
    ["/admin/messages/900539700124344320/send", {}, "account"],
    ["/admin/accounts/42", {}, "account"],
    ["/admin/ingest/transactions/42/run", {}, "account"],
    ["/admin/sales?account_id=42", {}, "account"],
    ["/admin/x?account=42", {}, "account"],
    ["/api/of/v2/users/me", { "X-Account-Id": "42" }, "account"],
    ["/admin/screens/inbox?cell=s02", {}, "cell"],
    ["/admin/screens/inbox", { "X-Cell-Id": "s02" }, "cell"],
    ["/admin/ingest/transactions/attribute", {}, null],
    ["/admin/mass-messages/1/cancel", {}, null],
    ["/api/of/v2/users/me", {}, null],
    ["/img", {}, null],
    ["/admin/view-lease", {}, null],
  ] as const)("%s %j → %s", (url, headers, want) => {
    expect(routeOf(url, h(headers))).toBe(want);
  });

  it("header beats query beats path, as Caddy's last-wins vars", () => {
    expect(accountOf("/admin/accounts/1?account=2", h({ "X-Account-Id": "3" }))).toBe("3");
    expect(accountOf("/admin/accounts/1?account=2", h())).toBe("2");
    expect(accountOf("/admin/accounts/1", h())).toBe("1");
  });

  it("keeps ids above 2^53 as strings", () => {
    expect(accountOf("/admin/messages/900539700124344321/x", h())).toBe("900539700124344321");
  });
});
