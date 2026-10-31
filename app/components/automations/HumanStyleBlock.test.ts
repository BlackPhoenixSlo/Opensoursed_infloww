import { describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";

import { usePageSave } from "./HumanStyleBlock";

type Edit = { type: "field"; v: number };

/** usePageSave over stub halves; `log` records the calls in order. */
function setup({
  pageFailed = false, styleFailed = false, pending = false, success = false, clean = true, pageUnsaved = false,
} = {}) {
  const log: string[] = [];
  const m = {
    isPending: pending, isSuccess: success, isError: pageFailed,
    error: pageFailed ? new Error("page boom") : null,
    reset: () => log.push("reset"),
  };
  const style = {
    save: () => { log.push("style.save"); },
    pending: false, clean, error: styleFailed ? new Error("") : null,
  };
  const { result } = renderHook(() => usePageSave<Edit>(m, style, pageUnsaved, (a) => log.push(`dispatch:${a.type}`)));
  return { ps: result.current, log };
}

describe("usePageSave edit", () => {
  it.each([
    { name: "no failed save: only dispatches", pageFailed: false, want: ["dispatch:field"] },
    { name: "failed page save: clears it, then dispatches", pageFailed: true, want: ["reset", "dispatch:field"] },
  ])("$name", ({ pageFailed, want }) => {
    const { ps, log } = setup({ pageFailed });
    ps.edit({ type: "field", v: 1 });
    expect(log).toEqual(want);
  });
});

describe("usePageSave save", () => {
  it("saves the style, records the draft as sent, then runs the page mutate", () => {
    const { ps, log } = setup();
    ps.save(() => log.push("mutate"));
    expect(log).toEqual(["style.save", "dispatch:saved", "mutate"]);
  });
});

describe("usePageSave verdict", () => {
  it.each([
    { name: "page saved, form and style clean", o: { success: true }, saved: true, error: null },
    { name: "edit since save", o: { success: true, pageUnsaved: true }, saved: false, error: null },
    { name: "style box unsaved", o: { success: true, clean: false }, saved: false, error: null },
    { name: "page save failed", o: { pageFailed: true }, saved: false, error: "page boom" },
    { name: "style save failed, no message", o: { styleFailed: true }, saved: false, error: "Save failed" },
  ])("$name", ({ o, saved, error }) => {
    const { ps } = setup(o);
    expect(ps.saved).toBe(saved);
    expect(ps.error).toBe(error);
  });
});
