import { afterEach, describe, expect, it, vi } from "vitest";

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
  };
  const answering = (byAccount: Record<string, { leased: string[]; warm: string }>) =>
    vi.fn(async (_u: string, i: RequestInit) => {
      const a = new Headers(i.headers).get("X-Account-Id");
      return new Response(JSON.stringify({ ttl_s: 60, ...(a ? byAccount[a] : { leased: [A, B], warm: "started" }) }));
    });
  afterEach(() => {
    document.head.querySelectorAll('meta[name="oi-cells"]').forEach((m) => m.remove());
    vi.unstubAllGlobals();
    resetActorRenewal();
  });
  const leaseCalls = (f: ReturnType<typeof answering>) => f.mock.calls.filter((c) => !c[0].startsWith("/auth/actor"));
  const post = async (b: LeaseBody) => (await import("@/lib/viewLease")).postLease(b);

  it("outside cell mode posts the body once with no account", async () => {
    const f = answering({});
    vi.stubGlobal("fetch", f);
    expect(await post(body)).toEqual({ leased: [A, B], ttl_s: 60, warm: "started" });
    expect(f).toHaveBeenCalledTimes(1);
    expect(new Headers(f.mock.calls[0][1].headers).has("X-Account-Id")).toBe(false);
    expect(JSON.parse(String(f.mock.calls[0][1].body))).toEqual(body);
  });

  it("in cell mode posts the same body once per Creator (selected once) and merges the answers", async () => {
    cells();
    const f = answering({ [A]: { leased: [A], warm: "none" }, [B]: { leased: [B], warm: "reused" } });
    vi.stubGlobal("fetch", f);
    expect(await post(body)).toEqual({ leased: [A, B], ttl_s: 60, warm: "reused" });
    expect(leaseCalls(f).map((c) => new Headers(c[1].headers).get("X-Account-Id"))).toEqual([A, B]);
    expect(leaseCalls(f).every((c) => String(c[1].body) === JSON.stringify(body))).toBe(true);
  });

  it("in cell mode a started warm on any Cell wins; a selected outside account_ids gets its own post", async () => {
    cells();
    const f = answering({ [A]: { leased: [A], warm: "started" }, [B]: { leased: [B], warm: "reused" } });
    vi.stubGlobal("fetch", f);
    expect((await post({ ...body, account_ids: [A] })).warm).toBe("started");
    expect(leaseCalls(f).map((c) => new Headers(c[1].headers).get("X-Account-Id"))).toEqual([A, B]);
  });

  it("in cell mode an empty lease posts nothing (no Cell to route to; the lease lapses by TTL)", async () => {
    cells();
    const f = answering({});
    vi.stubGlobal("fetch", f);
    expect(await post({ ...body, account_ids: [], selected: null })).toEqual({ leased: [], ttl_s: 0, warm: "none" });
    expect(f).not.toHaveBeenCalled();
  });
});
