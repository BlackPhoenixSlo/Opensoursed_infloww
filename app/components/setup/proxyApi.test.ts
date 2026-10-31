/** proxyOps: the relay calls a proxy change makes, in order. A wrong proxy on a Creator can get it banned. */
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";

vi.mock("@/lib/relay", () => ({ relay: { post: vi.fn() } }));

import { applyProxy, proxyOps, type ProxyChoice, type ProxyOp } from "@/components/setup/proxyApi";
import { relay } from "@/lib/relay";
const relayPost = relay.post as unknown as Mock;

const pool: ProxyChoice = { type: "infloww" };
const none: ProxyChoice = { type: "none" };
const custom = (label: string, ok: boolean | null = true): ProxyChoice => ({ type: "custom", label, ok });

describe("proxyOps", () => {
  it.each<[string, ProxyChoice, ProxyChoice, ProxyOp[]]>([
    ["same pool → no-op", pool, pool, []],
    ["same none → no-op", none, none, []],
    ["same custom → no-op (check state ignored)", custom("a", true), custom("a", null), []],
    ["none → pool", none, pool, [{ op: "bindPool" }, { op: "reload" }]],
    ["custom → pool: bind alone moves it off the custom proxy", custom("a"), pool, [{ op: "bindPool" }, { op: "reload" }]],
    ["pool → custom", pool, custom("b"), [{ op: "unbindPool" }, { op: "assign", label: "b" }, { op: "reload" }]],
    ["pool → none", pool, none, [{ op: "unbindPool" }, { op: "reload" }]],
    ["none → custom", none, custom("b"), [{ op: "assign", label: "b" }, { op: "reload" }]],
    ["custom → none", custom("a"), none, [{ op: "unbind", label: "a" }, { op: "reload" }]],
    ["custom label change", custom("a"), custom("b"),
      [{ op: "unbind", label: "a" }, { op: "assign", label: "b" }, { op: "reload" }]],
    ["custom → custom with no label yet: off the old one only", custom("a"), custom("", null),
      [{ op: "unbind", label: "a" }, { op: "reload" }]],
  ])("%s", (_, current, next, ops) => {
    expect(proxyOps(current, next)).toEqual(ops);
  });

  it("order: onto the pool, the proxy is bound before the session reloads", () => {
    for (const from of [none, custom("a")]) {
      const ops = proxyOps(from, pool).map((o) => o.op);
      expect(ops.indexOf("bindPool")).toBe(0);
      expect(ops.indexOf("reload")).toBe(1);
    }
  });

  it("order: off the old proxy, onto the new, reload last", () => {
    expect(proxyOps(custom("a"), custom("b")).map((o) => o.op)).toEqual(["unbind", "assign", "reload"]);
  });
});

describe("applyProxy wire calls", () => {
  beforeEach(() => { relayPost.mockReset(); relayPost.mockResolvedValue({}); });

  it.each<[string, ProxyChoice, ProxyChoice, unknown[][]]>([
    ["none → pool", none, pool, [
      ["/admin/proxy-pool/assign", { account_id: "a/1" }],
      ["/admin/reload-session?account_id=a%2F1"],
    ]],
    ["pool → custom", pool, custom("x y"), [
      ["/admin/proxy-pool/unbind", { account_id: "a/1" }],
      ["/admin/proxies/assign", { label: "x y", account_id: "a/1" }],
      ["/admin/reload-session?account_id=a%2F1"],
    ]],
    ["custom label change", custom("x y"), custom("z"), [
      ["/admin/proxies/x%20y/unbind", { account_id: "a/1" }],
      ["/admin/proxies/assign", { label: "z", account_id: "a/1" }],
      ["/admin/reload-session?account_id=a%2F1"],
    ]],
    ["same → nothing sent", custom("z"), custom("z"), []],
  ])("%s", async (_, current, next, calls) => {
    await applyProxy("a/1", current, next);
    expect(relayPost.mock.calls).toEqual(calls);
  });

  it("a failed call stops the rest (no reload onto a half-applied proxy)", async () => {
    relayPost.mockRejectedValueOnce(new Error("409"));
    await expect(applyProxy("a", custom("x"), custom("y"))).rejects.toThrow("409");
    expect(relayPost).toHaveBeenCalledTimes(1);
  });
});
