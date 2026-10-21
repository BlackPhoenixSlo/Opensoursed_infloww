/**
 * chatDrafts — the composer's per-chat draft text: restored per Fan, live
 * for the Fan List, and cleared when the composer empties (a send).
 *
 * Fixture identifiers are invented (this repo mirrors to a public one).
 */
import { afterEach, describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { chatDraftKey, useChatDraft, useChatDraftText } from "./chatDrafts";

const A = "100000001";

afterEach(() => sessionStorage.clear());

describe("chatDrafts", () => {
  it("keeps a chat's text across a remount, per Fan, and drops it once blank", () => {
    const first = renderHook(() => useChatDraft(A, 200000001));
    act(() => first.result.current[1]("half a reply"));
    first.unmount();

    expect(renderHook(() => useChatDraft(A, 200000002)).result.current[0]).toBe("");
    const again = renderHook(() => useChatDraft(A, 200000001));
    expect(again.result.current[0]).toBe("half a reply");

    act(() => again.result.current[1]("   "));
    expect(sessionStorage.getItem(chatDraftKey(A, 200000001))).toBeNull();
  });

  it("stores nothing without a chat (a mass composer)", () => {
    const h = renderHook(() => useChatDraft(A, null));
    act(() => h.result.current[1]("mass text"));
    expect(sessionStorage.length).toBe(0);
  });

  it("tells a Fan List row live when its chat's draft changes", () => {
    const row = renderHook(() => useChatDraftText(A, 200000001));
    const composer = renderHook(() => useChatDraft(A, 200000001));
    expect(row.result.current).toBe("");
    act(() => composer.result.current[1]("typing…"));
    expect(row.result.current).toBe("typing…");
    act(() => composer.result.current[1](""));
    expect(row.result.current).toBe("");
  });
});
