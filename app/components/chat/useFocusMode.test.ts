/**
 * useFocusMode's settings (W4 4.15c): Pause incoming messages and Hide chats
 * with muted notifications. Fixture ids are invented.
 */
import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import type { OFChatItem } from "@/lib/relay";
import { useFocusMode } from "./useFocusMode";
import { FOCUS_MODE_DEFAULTS, type FocusModeSettings } from "./useFocusModeSettings";

const chat = (id: number, at: string, extra: Partial<OFChatItem> = {}) => ({
  withUser: { id, name: `Fixture Fan ${id}`, username: `fan${id}` },
  lastMessage: { id: id + 1, text: "hi", fromUser: { id }, createdAt: at },
  __accountId: "100000001",
  ...extra,
}) as OFChatItem;

const PLAIN = chat(200000001, "2026-10-20T10:00:00Z");
const MUTED = chat(200000002, "2026-10-20T09:00:00Z", { isMutedNotifications: true });
const OTHER = chat(200000003, "2026-10-20T08:00:00Z");
const NEWER = chat(200000004, "2026-10-20T11:00:00Z");

function setup(settings: FocusModeSettings, liveRows = [PLAIN, MUTED, OTHER]) {
  const hook = renderHook((p: { liveRows: OFChatItem[]; settings: FocusModeSettings }) => useFocusMode({
    liveRows: p.liveRows, listKey: "acct|all", settled: true, available: true,
    fromFan: () => true, refresh: vi.fn(async () => ({ isError: false })), settings: p.settings,
  }), { initialProps: { liveRows, settings } });
  act(() => hook.result.current.setFocusMode(true));
  return hook;
}
const ids = (rows: OFChatItem[]) => rows.map((c) => c.withUser.id);

describe("useFocusMode settings", () => {
  it("defaults pause the list: a newer chat waits behind the new-messages count", () => {
    const hook = setup(FOCUS_MODE_DEFAULTS);
    hook.rerender({ liveRows: [NEWER, PLAIN, MUTED, OTHER], settings: FOCUS_MODE_DEFAULTS });
    expect(ids(hook.result.current.rows)).toEqual(ids([PLAIN, MUTED, OTHER]));
    expect(hook.result.current.newCount).toBe(1);
  });

  it("with Pause off the list stays live", () => {
    const live = { ...FOCUS_MODE_DEFAULTS, pause: false };
    const hook = setup(live);
    hook.rerender({ liveRows: [NEWER, PLAIN, MUTED, OTHER], settings: live });
    expect(ids(hook.result.current.rows)).toEqual(ids([NEWER, PLAIN, MUTED, OTHER]));
    expect(hook.result.current.newCount).toBe(0);
  });

  it("hides muted chats only while the setting and Focus mode are on", () => {
    const hide = { ...FOCUS_MODE_DEFAULTS, hideMuted: true };
    const hook = setup(hide);
    expect(ids(hook.result.current.rows)).toEqual(ids([PLAIN, OTHER]));
    hook.rerender({ liveRows: [PLAIN, MUTED, OTHER], settings: FOCUS_MODE_DEFAULTS });
    expect(ids(hook.result.current.rows)).toEqual(ids([PLAIN, MUTED, OTHER]));
    hook.rerender({ liveRows: [PLAIN, MUTED, OTHER], settings: hide });
    act(() => hook.result.current.setFocusMode(false));
    expect(ids(hook.result.current.rows)).toEqual(ids([PLAIN, MUTED, OTHER]));
  });

  it("a frozen row muted since the freeze leaves while the hide is on", () => {
    const hide = { ...FOCUS_MODE_DEFAULTS, hideMuted: true };
    const hook = setup(hide);
    expect(ids(hook.result.current.rows)).toEqual(ids([PLAIN, OTHER]));
    hook.rerender({ liveRows: [PLAIN, MUTED, { ...OTHER, isMutedNotifications: true }], settings: hide });
    expect(ids(hook.result.current.rows)).toEqual(ids([PLAIN]));
  });
});
