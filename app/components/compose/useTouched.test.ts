import { useReducer } from "react";
import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { isAudienceSeed, useTouched } from "./useTouched";

type S = { accountId: string | null; text: string };
type A = { type: "setAccount"; id: string } | { type: "seedExclude" } | { type: "text"; v: string };
const reducer = (s: S, a: A): S =>
  a.type === "setAccount" ? { ...s, accountId: a.id } : a.type === "text" ? { ...s, text: a.v } : s;

function run(accountId: string | null = null) {
  return renderHook(() => {
    const [s, raw] = useReducer(reducer, { accountId, text: "" });
    return useTouched(s, raw, isAudienceSeed);
  });
}

describe("useTouched", () => {
  it("the seeding alone (first account, exclude seed) leaves it clean", () => {
    const h = run();
    act(() => h.result.current.dispatch({ type: "setAccount", id: "a" }));
    act(() => h.result.current.dispatch({ type: "seedExclude" }));
    expect(h.result.current.touched).toBe(false);
  });
  it("a user action before the seeding stays touched after it", () => {
    const h = run();
    act(() => h.result.current.dispatch({ type: "text", v: "x" }));
    act(() => h.result.current.dispatch({ type: "setAccount", id: "a" }));
    act(() => h.result.current.dispatch({ type: "seedExclude" }));
    expect(h.result.current.touched).toBe(true);
  });
  it("switching from a picked account is the user's", () => {
    const h = run("a");
    act(() => h.result.current.dispatch({ type: "setAccount", id: "b" }));
    expect(h.result.current.touched).toBe(true);
  });
  it("once touched it stays touched until unmount, even when the edit is reverted (declared)", () => {
    const h = run("a");
    act(() => h.result.current.dispatch({ type: "text", v: "x" }));
    act(() => h.result.current.dispatch({ type: "text", v: "" }));
    expect(h.result.current.touched).toBe(true);
  });
});
