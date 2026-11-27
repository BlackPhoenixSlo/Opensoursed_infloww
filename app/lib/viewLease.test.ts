import { afterEach, describe, expect, it, vi } from "vitest";

import { resetCellFlagForTests } from "@/lib/cellFlag";
import { resetActorRenewal } from "@/lib/actorRenew";
import type { LeaseBody } from "@/lib/viewLeaseState";

describe("tabId", () => {
  afterEach(() => {
    window.sessionStorage.clear();
    vi.resetModules();
  });

  const load = async () => (await import("@/lib/viewLease")).tabId;

  it("is stable within one document load", async () => {
    const tabId = await load();
    expect(tabId()).toBe(tabId());
  });

  it("is not read from sessionStorage (a popout or a duplicated tab copies it)", async () => {
    window.sessionStorage.setItem("chatterly:view-lease-tab", "copied-from-opener");
    const tabId = await load();
    expect(tabId()).not.toBe("copied-from-opener");
  });

  it("differs per document load", async () => {
    const first = (await load())();
    vi.resetModules();
    const second = (await load())();
    expect(second).not.toBe(first);
  });
});

describe("postLease", () => {
  const A = "900539700124344320";
  const B = "900539700124344321";
  const body: LeaseBody = { tab: "t1", account_ids: [A, B], selected: B, opened: true };
  const cells = () => {
    const m = document.createElement("meta");
    m.name = "oi-cells";
    document.head.append(m);
    resetCellFlagForTests();
  };
  const answering = (byAccount: Record<string, { leased: string[]; warm: string }>) =>
    vi.fn(async (_u: string, i: RequestInit) => {
      if (_u === "/auth/cells") return new Response(JSON.stringify({
        actor: "owner", grant_gen: 1, placement_gen: 1, cells: ["a", "b"],
        accounts: [{ account_id: A, cell: "a" }, { account_id: B, cell: "b" }],
      }));
      const a = new Headers(i.headers).get("X-Cell-Id");
      if (a && !byAccount[a]) throw new Error("offline");
      return new Response(JSON.stringify({ ttl_s: 60, ...(a ? byAccount[a] : { leased: [A, B], warm: "started" }) }));
    });
  afterEach(async () => {
    (await import("@/lib/cellMap")).forgetCellMap();
    document.head.querySelectorAll('meta[name="oi-cells"]').forEach((m) => m.remove());
    resetCellFlagForTests();
    vi.unstubAllGlobals();
    resetActorRenewal();
    vi.resetModules();
  });
  const leaseCalls = (f: ReturnType<typeof answering>) => f.mock.calls.filter((c) => c[0] === "/admin/view-lease");
  const post = async (b: LeaseBody) => (await import("@/lib/viewLease")).postLease(b);

  it("outside cell mode posts the body once with no account", async () => {
    const f = answering({});
    vi.stubGlobal("fetch", f);
    expect(await post(body)).toEqual({ leased: [A, B], ttl_s: 60, warm: "started" });
    expect(f).toHaveBeenCalledTimes(1);
    expect(new Headers(f.mock.calls[0][1].headers).has("X-Account-Id")).toBe(false);
    expect(JSON.parse(String(f.mock.calls[0][1].body))).toEqual(body);
  });

  it("scopes each body and merges healthy Cells if one is offline", async () => {
    cells();
    const f = answering({ b: { leased: [B], warm: "reused" } });
    vi.stubGlobal("fetch", f);
    expect(await post(body)).toEqual({ leased: [B], ttl_s: 60, warm: "reused" });
    expect(leaseCalls(f).map((c) => new Headers(c[1].headers).get("X-Cell-Id"))).toEqual(["a", "b"]);
    expect(leaseCalls(f).map((c) => JSON.parse(String(c[1].body)))).toEqual([
      { ...body, account_ids: [A], selected: null },
      { ...body, account_ids: [B] },
    ]);
  });

  it("rejects when every granted Cell is offline so opened stays pending", async () => {
    cells();
    vi.stubGlobal("fetch", answering({}));
    await expect(post(body)).rejects.toThrow("offline");
  });

  it("sends opened to granted Cells without held Creators", async () => {
    cells();
    const f = answering({ a: { leased: [], warm: "started" }, b: { leased: [], warm: "reused" } });
    vi.stubGlobal("fetch", f);
    const empty = { ...body, account_ids: [], selected: null };
    expect(await post(empty)).toEqual({ leased: [], ttl_s: 60, warm: "started" });
    expect(leaseCalls(f).map((c) => JSON.parse(String(c[1].body)))).toEqual([empty, empty]);
  });

  it("warms a recovered Cell and releases the dropped Cell once", async () => {
    cells();
    const answers = { b: { leased: [B], warm: "reused" } } as Record<string, { leased: string[]; warm: string }>;
    const f = answering(answers);
    vi.stubGlobal("fetch", f);
    await post(body);
    answers.a = { leased: [A], warm: "started" };
    const next = { ...body, account_ids: [B], opened: false };
    await post(next);
    await post(next);
    expect(leaseCalls(f).slice(2).map(([_, init]) => [
      new Headers(init.headers).get("X-Cell-Id"), JSON.parse(String(init.body)),
    ])).toEqual([
      ["a", { ...body, account_ids: [], selected: null }],
      ["b", next],
      ["b", next],
    ]);
  });

  it("releases a healthy Cell on its last held Creator's removal", async () => {
    cells();
    const f = answering({ a: { leased: [A], warm: "started" }, b: { leased: [B], warm: "reused" } });
    vi.stubGlobal("fetch", f);
    await post(body);
    const next = { ...body, account_ids: [B], opened: false };
    await post(next);
    await post(next);
    const releases = leaseCalls(f).slice(2).filter(([_, init]) => new Headers(init.headers).get("X-Cell-Id") === "a");
    expect(releases.map(([_, init]) => JSON.parse(String(init.body)))).toEqual([
      { ...next, account_ids: [], selected: null },
    ]);
  });

});
