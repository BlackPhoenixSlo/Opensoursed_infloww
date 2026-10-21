/**
 * The page SSE override: the bus follows the override while it is mounted,
 * `eventScope` reports what the bus follows, and unmount hands the bus back
 * to the inbox scope — which the override never touches (not on a hard load,
 * not when the scope is changed while it is mounted).
 */
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";

const busScope = vi.fn();
vi.mock("@/lib/events", () => ({ eventBus: { setScope: (s: string) => busScope(s) } }));
vi.mock("@/hooks/useAccountStateEvents", () => ({ useAccountStateEvents: () => {} }));

import { ScopeProvider, useEventScopeOverride, useScope } from "@/contexts/ScopeContext";

function Focus() { useEventScopeOverride("all"); return null; }
let focusOn = true;
const wrapper = ({ children }: { children: ReactNode }) => (
  <ScopeProvider>{focusOn && <Focus />}{children}</ScopeProvider>
);

afterEach(() => { cleanup(); busScope.mockClear(); window.localStorage.clear(); });

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
