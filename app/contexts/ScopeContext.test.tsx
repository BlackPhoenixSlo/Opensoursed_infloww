/**
 * The page SSE override: the bus follows the override while it is mounted,
 * `eventScope` reports what the bus follows, and unmount hands the bus back
 * to the inbox scope — which the override never touches (not on a hard load,
 * not when the scope is changed while it is mounted).
 */
import { useEffect, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";

const busScope = vi.fn();
vi.mock("@/lib/events", () => ({ eventBus: { setScope: (s: string) => busScope(s) } }));
vi.mock("@/hooks/useAccountStateEvents", () => ({ useAccountStateEvents: () => {} }));

import { cookieValue } from "@/lib/screenEntry";
import { ScopeProvider, useDropWatcherScope, useEventScopeOverride, useScope, WATCHER_PICK_KEY, WatcherScope } from "@/contexts/ScopeContext";

function Focus() { useEventScopeOverride("all"); return null; }
let focusOn = true;
const wrapper = ({ children }: { children: ReactNode }) => (
  <ScopeProvider>{focusOn && <Focus />}{children}</ScopeProvider>
);

afterEach(() => { cleanup(); busScope.mockClear(); window.localStorage.clear(); });

describe("the saved scope's cookie (lib/screenEntry.ts: a document load's inbox bundle guess)", () => {
  const SCOPE_COOKIE = "chatterly_scope";
  afterEach(() => { document.cookie = `${SCOPE_COOKIE}=; path=/; max-age=0`; });
  const saved = () => cookieValue(document.cookie, SCOPE_COOKIE);

  it("mirrors one bit of the saved scope (model or all, never the Creator's id) on load and on every saved pick", async () => {
    window.localStorage.setItem("chatterly:scope", "model:m1");
    focusOn = false;
    const { result } = renderHook(() => useScope(), { wrapper });
    await act(async () => {});
    expect(saved()).toBe("model");
    expect(document.cookie).not.toContain("m1");
    act(() => result.current.setScope({ kind: "all" }));
    expect(saved()).toBe("all");
    act(() => result.current.setScope({ kind: "model", accountId: "m2" }, { persist: false }));
    expect(saved()).toBe("all");
    act(() => result.current.setScope({ kind: "model", accountId: "m2" }));
    expect(saved()).toBe("model");
    expect(document.cookie).not.toContain("m2");
  });
});

describe("useEventScopeOverride", () => {
  it("points the bus (and eventScope) at the override while mounted, then back to the saved scope", async () => {
    window.localStorage.setItem("chatterly:scope", "model:m1");
    focusOn = true;
    const { result, rerender } = renderHook(() => useScope(), { wrapper });
    await act(async () => {});
    expect(result.current.eventScope).toBe("all");
    expect(busScope).toHaveBeenLastCalledWith("all");
    expect(result.current.scope).toEqual({ kind: "model", accountId: "m1" });

    focusOn = false;
    rerender();
    await act(async () => {});
    expect(result.current.eventScope).toBe("model:m1");
    expect(busScope).toHaveBeenLastCalledWith("model:m1");
    expect(window.localStorage.getItem("chatterly:scope")).toBe("model:m1");
  });

  it("a scope picked while the override is mounted is kept when it unmounts", async () => {
    window.localStorage.setItem("chatterly:scope", "model:m1");
    focusOn = true;
    const { result, rerender } = renderHook(() => useScope(), { wrapper });
    await act(async () => {});
    act(() => result.current.setScope({ kind: "model", accountId: "m2" }));
    expect(busScope).toHaveBeenLastCalledWith("all");

    focusOn = false;
    rerender();
    await act(async () => {});
    expect(result.current.scope).toEqual({ kind: "model", accountId: "m2" });
    expect(busScope).toHaveBeenLastCalledWith("model:m2");
  });
});

describe("WatcherScope", () => {
  const W = "w1";
  const pick = (id: string, over: string) => JSON.stringify({ id, over });
  function Probe({ out }: { out: { inner?: ReturnType<typeof useScope> } }) { out.inner = useScope(); return null; }
  /** A Pop-out's `?account=`: a child's mount effect picks `id` for this window only. */
  function PopOut({ id }: { id: string }) {
    const { setScope } = useScope();
    useEffect(() => { setScope({ kind: "model", accountId: id }, { persist: false }); }, [setScope, id]);
    return null;
  }
  function setup({ ids = [W], pickable = ids, loaded = true, pop }: { ids?: string[]; pickable?: string[]; loaded?: boolean; pop?: string } = {}) {
    const out: { inner?: ReturnType<typeof useScope> } = {};
    const wrap = ({ children }: { children: ReactNode }) => (
      <ScopeProvider>{children}<WatcherScope watcherIds={ids} pickable={pickable} loaded={loaded}>
        <Probe out={out} />{pop && <PopOut id={pop} />}
      </WatcherScope></ScopeProvider>
    );
    const r = renderHook(() => useScope(), { wrapper: wrap });
    return { outer: () => r.result.current, inner: () => out.inner!, rerender: r.rerender };
  }

  it("a watcher pick is seen inside only: outer scope, its saved value and the SSE scope stay the Creator's", async () => {
    window.localStorage.setItem("chatterly:scope", "model:c1");
    const { outer, inner } = setup();
    await act(async () => {});
    act(() => inner().setScope({ kind: "model", accountId: W }));
    expect(inner().scope).toEqual({ kind: "model", accountId: W });
    expect(inner().accountId).toBe(W);
    expect(outer().scope).toEqual({ kind: "model", accountId: "c1" });
    expect(window.localStorage.getItem("chatterly:scope")).toBe("model:c1");
    expect(window.localStorage.getItem(WATCHER_PICK_KEY)).toBe(pick(W, "model:c1"));
    expect(busScope).toHaveBeenLastCalledWith("model:c1");
    expect(inner().eventScope).toBe("model:c1");
  });

  it("a Creator pick clears the watcher pick and goes to the outer scope", async () => {
    window.localStorage.setItem(WATCHER_PICK_KEY, pick(W, "all"));
    const { outer, inner } = setup();
    await act(async () => {});
    expect(inner().accountId).toBe(W);
    act(() => inner().setScope({ kind: "model", accountId: "c2" }));
    expect(inner().scope).toEqual({ kind: "model", accountId: "c2" });
    expect(outer().scope).toEqual({ kind: "model", accountId: "c2" });
    expect(window.localStorage.getItem(WATCHER_PICK_KEY)).toBeNull();
    expect(window.localStorage.getItem("chatterly:scope")).toBe("model:c2");
  });

  it("persist:false (a Pop-out window) picks the watcher without saving it", async () => {
    const { inner } = setup();
    await act(async () => {});
    act(() => inner().setScope({ kind: "model", accountId: W }, { persist: false }));
    expect(inner().accountId).toBe(W);
    expect(window.localStorage.getItem(WATCHER_PICK_KEY)).toBeNull();
  });

  it("a Pop-out's Creator, picked in a child's mount effect, wins over the saved watcher pick", async () => {
    window.localStorage.setItem("chatterly:scope", "model:c1");
    window.localStorage.setItem(WATCHER_PICK_KEY, pick(W, "model:c1"));
    const { outer, inner } = setup({ pop: "c3" });
    await act(async () => {});
    expect(inner().accountId).toBe("c3");
    expect(outer().accountId).toBe("c3");
    // Not saved: the opener keeps its scope and its watcher pick.
    expect(window.localStorage.getItem("chatterly:scope")).toBe("model:c1");
    expect(window.localStorage.getItem(WATCHER_PICK_KEY)).toBe(pick(W, "model:c1"));
  });

  it("a Creator picked elsewhere since (the saved scope changed) wins over the saved watcher pick", async () => {
    window.localStorage.setItem(WATCHER_PICK_KEY, pick(W, "model:c1"));
    window.localStorage.setItem("chatterly:scope", "model:c2");
    const { inner } = setup();
    await act(async () => {});
    expect(inner().accountId).toBe("c2");
  });

  it("an outer scope change while mounted (from outside the subtree) ends the watcher pick and clears the saved one", async () => {
    window.localStorage.setItem("chatterly:scope", "model:c1");
    const { outer, inner } = setup();
    await act(async () => {});
    act(() => inner().setScope({ kind: "model", accountId: W }));
    expect(inner().accountId).toBe(W);
    act(() => outer().setScope({ kind: "model", accountId: "c2" }));
    expect(inner().accountId).toBe("c2");
    await act(async () => {});
    expect(window.localStorage.getItem(WATCHER_PICK_KEY)).toBeNull();
    // A change back to the old Creator does not bring it back.
    act(() => outer().setScope({ kind: "model", accountId: "c1" }));
    expect(inner().accountId).toBe("c1");
  });

  it("does not loop with useDropWatcherScope: a watcher pick never reaches the outer scope it watches", async () => {
    window.localStorage.setItem("chatterly:scope", "model:c1");
    const out: { inner?: ReturnType<typeof useScope> } = {};
    function Drop() { useDropWatcherScope([W]); return null; }
    let renders = 0;
    function Count() { renders += 1; return null; }
    const r = renderHook(() => useScope(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <ScopeProvider><Drop />{children}<WatcherScope watcherIds={[W]} pickable={[W]} loaded><Probe out={out} /><Count /></WatcherScope></ScopeProvider>
      ),
    });
    await act(async () => {});
    act(() => out.inner!.setScope({ kind: "model", accountId: W }));
    await act(async () => {});
    const settled = renders;
    await act(async () => {});
    expect(renders).toBe(settled);
    expect(out.inner!.accountId).toBe(W);
    expect(r.result.current.scope).toEqual({ kind: "model", accountId: "c1" });
    expect(window.localStorage.getItem("chatterly:scope")).toBe("model:c1");
  });

  it("a saved pick that is no longer a watcher is dropped once the list is loaded", async () => {
    window.localStorage.setItem("chatterly:scope", "model:c1");
    window.localStorage.setItem(WATCHER_PICK_KEY, pick("gone", "model:c1"));
    const { inner } = setup({ ids: [W], loaded: true });
    await act(async () => {});
    expect(inner().accountId).toBe("c1");
    expect(window.localStorage.getItem(WATCHER_PICK_KEY)).toBeNull();
  });

  it("a saved pick of a watcher OF Manager does not list (no session) is dropped, never active", async () => {
    window.localStorage.setItem("chatterly:scope", "model:c1");
    window.localStorage.setItem(WATCHER_PICK_KEY, pick(W, "model:c1"));
    const { outer, inner } = setup({ ids: [W], pickable: [], loaded: true });
    await act(async () => {});
    expect(inner().accountId).toBe("c1");
    expect(window.localStorage.getItem(WATCHER_PICK_KEY)).toBeNull();
    // Picking it anyway never reaches the outer scope.
    act(() => inner().setScope({ kind: "model", accountId: W }, { persist: false }));
    expect(outer().accountId).toBe("c1");
  });

  it("before the list is loaded a saved pick is kept (not shown, not dropped)", async () => {
    window.localStorage.setItem(WATCHER_PICK_KEY, pick(W, "all"));
    const { inner } = setup({ ids: [], loaded: false });
    await act(async () => {});
    expect(inner().accountId).toBeNull();
    expect(window.localStorage.getItem(WATCHER_PICK_KEY)).toBe(pick(W, "all"));
  });
});

describe("useDropWatcherScope", () => {
  function setup(ids: string[]) {
    return renderHook(({ list }) => { useDropWatcherScope(list); return useScope(); }, {
      wrapper: ({ children }: { children: ReactNode }) => <ScopeProvider>{children}</ScopeProvider>,
      initialProps: { list: ids },
    });
  }

  it("a saved app scope naming a watcher is reset to all, saved too", async () => {
    window.localStorage.setItem("chatterly:scope", "model:w1");
    const { result } = setup(["w1"]);
    await act(async () => {});
    expect(result.current.scope).toEqual({ kind: "all" });
    expect(window.localStorage.getItem("chatterly:scope")).toBe("all");
    expect(busScope).toHaveBeenLastCalledWith("all");
  });

  it("keeps a Creator's scope, and keeps any scope while the watchers are not read yet", async () => {
    window.localStorage.setItem("chatterly:scope", "model:c1");
    const { result, rerender } = setup([]);
    await act(async () => {});
    expect(result.current.accountId).toBe("c1");
    rerender({ list: ["w1"] });
    await act(async () => {});
    expect(result.current.accountId).toBe("c1");
    expect(window.localStorage.getItem("chatterly:scope")).toBe("model:c1");
  });

  it("a scope that turns into a watcher's once the list lands is reset", async () => {
    window.localStorage.setItem("chatterly:scope", "model:w1");
    const { result, rerender } = setup([]);
    await act(async () => {});
    expect(result.current.accountId).toBe("w1");
    rerender({ list: ["w1"] });
    await act(async () => {});
    expect(result.current.scope).toEqual({ kind: "all" });
  });
});
