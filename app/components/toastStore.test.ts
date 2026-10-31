import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";

const relayGet = vi.fn();
vi.mock("@/lib/relay", () => ({ relay: { get: (...args: unknown[]) => relayGet(...args) } }));

import { DEFAULT_NOTIF_SETTINGS, readNotifHistory, type NotifSettings } from "@/lib/notifSettings";
import { ofUserNameKey } from "@/hooks/useOFUser";
import { notificationHref } from "@/lib/notificationLink";
import type { ChatTarget } from "@/hooks/useInboxRealtime";
import {
  MAX_SEEN_IDS,
  MAX_TOASTS_VISIBLE,
  TOAST_TTL_MS,
  claimUnseen,
  deliverDecision,
  deliverNotification,
  dismissToast,
  dmArrival,
  extractAvatarFromHtml,
  extractUsernameFromHtml,
  patchToastHref,
  purchaseArrival,
  pushToast,
  resolveUsernameId,
  toastArrival,
  useToastStack,
  type Arrival,
  type Toast,
} from "./toastStore";

// The store is module state shared by every test here, so each test claims
// under its own account ids and lets its toasts expire before the next.

describe("claimUnseen", () => {
  it.each([
    // [claims as [aid, id], expected results]
    [[["c1", "1"], ["c1", "1"]], [true, false]],
    [[["c2", "1"], ["c3", "1"]], [true, true]],
    [[["c4", "1"], ["c4", "2"], ["c4", "1"]], [true, true, false]],
  ])("%j → %j", (claims, want) => {
    expect(claims.map(([aid, id]) => claimUnseen(aid, id))).toEqual(want);
  });

  it("evicts the oldest ids past MAX_SEEN_IDS", () => {
    for (let i = 0; i <= MAX_SEEN_IDS; i++) expect(claimUnseen("evict", String(i))).toBe(true);
    // id 0 was pushed out by the (MAX_SEEN_IDS + 1)th; id 1 is still held.
    expect(claimUnseen("evict", "1")).toBe(false);
    expect(claimUnseen("evict", "0")).toBe(true);
  });
});

function toast(accountId: string | null, id: string, over: Partial<Toast> = {}): Toast {
  return {
    id, accountId, typeKey: null, rawType: "", user: null, text: id,
    createdAt: 0, bubble: false, href: null, expiresAt: Date.now() + TOAST_TTL_MS, ...over,
  };
}

describe("toast stack", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => {
    act(() => { vi.runAllTimers(); });
    vi.useRealTimers();
  });
  const ids = (ts: Toast[]) => ts.map((t) => `${t.accountId}:${t.id}`);

  it("dedupes per account + id, and dismiss is scoped to the account", () => {
    const { result } = renderHook(() => useToastStack());
    act(() => {
      pushToast(toast("a", "1"));
      pushToast(toast("a", "1"));
      pushToast(toast("b", "1"));
      pushToast(toast(null, "1"));
    });
    expect(ids(result.current)).toEqual(["a:1", "b:1", "null:1"]);
    act(() => dismissToast("a", "1"));
    expect(ids(result.current)).toEqual(["b:1", "null:1"]);
    act(() => dismissToast(null, "1"));
    expect(ids(result.current)).toEqual(["b:1"]);
  });

  it(`keeps the newest ${MAX_TOASTS_VISIBLE} and expires each after its TTL`, () => {
    const { result } = renderHook(() => useToastStack());
    act(() => { for (let i = 0; i < MAX_TOASTS_VISIBLE + 1; i++) pushToast(toast("cap", String(i))); });
    expect(result.current).toHaveLength(MAX_TOASTS_VISIBLE);
    expect(result.current[0].id).toBe("1");
    act(() => { vi.advanceTimersByTime(TOAST_TTL_MS - 1); });
    expect(result.current).toHaveLength(MAX_TOASTS_VISIBLE);
    act(() => { vi.advanceTimersByTime(1); });
    expect(result.current).toHaveLength(0);
  });

  it("patchToastHref patches only that account's card", () => {
    const { result } = renderHook(() => useToastStack());
    act(() => { pushToast(toast("p1", "9")); pushToast(toast("p2", "9")); });
    act(() => patchToastHref("p2", "9", "/chat/42"));
    expect(result.current.map((t) => t.href)).toEqual([null, "/chat/42"]);
  });
});

describe("resolveUsernameId", () => {
  beforeEach(() => { relayGet.mockReset(); });

  it("concurrent lookups for one username share one request, and the id is kept as sent", async () => {
    let release!: (v: unknown) => void;
    relayGet.mockReturnValueOnce(new Promise((r) => { release = r; }));
    const qc = new QueryClient();
    const a = resolveUsernameId("r1", "jim", qc);
    const b = resolveUsernameId("r1", "jim", qc);
    release({ id: "900805852249276416", name: "Jim", username: "jim" });
    expect(await Promise.all([a, b])).toEqual(["900805852249276416", "900805852249276416"]);
    expect(relayGet).toHaveBeenCalledTimes(1);
    expect(relayGet).toHaveBeenCalledWith("/api/of/v2/users/jim", { accountId: "r1" });
    expect(qc.getQueryData(ofUserNameKey("r1", "900805852249276416"))).toMatchObject({ name: "Jim" });
    // Cached: no second read.
    expect(await resolveUsernameId("r1", "jim", qc)).toBe("900805852249276416");
    expect(relayGet).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["a failed read", () => relayGet.mockRejectedValueOnce(new Error("502"))],
    ["a reply with no valid id", () => relayGet.mockResolvedValueOnce({ id: null, username: "x" })],
  ])("%s is null and not cached — the next lookup reads again", async (_label, arrange) => {
    const qc = new QueryClient();
    const aid = `r-${_label}`;
    arrange();
    expect(await resolveUsernameId(aid, "ann", qc)).toBeNull();
    relayGet.mockResolvedValueOnce({ id: 77, username: "ann" });
    expect(await resolveUsernameId(aid, "ann", qc)).toBe(77);
    expect(relayGet).toHaveBeenCalledTimes(2);
  });

  it("is scoped per account: one username on two Creators is two fans", async () => {
    const qc = new QueryClient();
    relayGet.mockResolvedValueOnce({ id: 1 }).mockResolvedValueOnce({ id: 2 });
    expect(await resolveUsernameId("s1", "sam", qc)).toBe(1);
    expect(await resolveUsernameId("s2", "sam", qc)).toBe(2);
  });
});

describe("deliverDecision", () => {
  const base: NotifSettings = {
    ...DEFAULT_NOTIF_SETTINGS,
    enabled: true,
    toast: { ...DEFAULT_NOTIF_SETTINGS.toast, tip: true, message: true, favorited: false },
    bubble: { ...DEFAULT_NOTIF_SETTINGS.bubble, tip: true, message: false },
  };
  const arrival = (over: Partial<Arrival>): Arrival => ({
    id: "n1", accountId: "acc", typeKey: "tip", rawType: "tip", user: { id: 5, name: "Jim" },
    text: "sent you a $5 tip", createdMs: 1_000, href: "/chat/5?refresh=media", ...over,
  });

  it.each([
    // [label, settings, arrival, toasts?, bubble]
    ["master off mutes", { ...base, enabled: false }, arrival({}), false, false],
    ["type toggled off mutes", base, arrival({ typeKey: "favorited" }), false, false],
    ["type on with bubble", base, arrival({}), true, true],
    ["type on, no bubble", base, arrival({ typeKey: "message" }), true, false],
    ["unknown type pings, never bubbles", base, arrival({ typeKey: null, rawType: "odd" }), true, false],
  ] as const)("%s", (_l, settings, n, toasts, bubble) => {
    const t = deliverDecision(settings, n, 50_000);
    expect(t !== null).toBe(toasts);
    if (t) {
      expect(t).toEqual({
        id: n.id, accountId: n.accountId, typeKey: n.typeKey, rawType: n.rawType, user: n.user,
        text: n.text, createdAt: n.createdMs, bubble, href: n.href, expiresAt: 50_000 + TOAST_TTL_MS,
      });
    }
  });

});

describe("deliverNotification: history always, pings gated", () => {
  beforeEach(() => { vi.useFakeTimers(); window.localStorage.clear(); });
  afterEach(() => {
    act(() => { vi.runAllTimers(); });
    vi.useRealTimers();
  });
  const settings: NotifSettings = {
    ...DEFAULT_NOTIF_SETTINGS, enabled: true, osPing: false,
    toast: { ...DEFAULT_NOTIF_SETTINGS.toast, tip: true },
  };
  // Dated now: the history mirror prunes rows older than its TTL on read.
  const arrival = (): Arrival => ({
    id: "d1", accountId: "deliver", typeKey: "tip", rawType: "tip", user: { id: 5, name: "Jim" },
    text: "sent you a $5 tip", historyText: "<b>sent</b> you a $5 tip", createdMs: Date.now(), href: null,
  });

  it.each([
    // [label, settings, toasts?]
    ["muted (master off)", { ...settings, enabled: false }, false],
    ["muted (type off)", { ...settings, toast: { ...settings.toast, tip: false } }, false],
    ["on", settings, true],
  ] as const)("%s: the history row is written either way", (_l, s, toasts) => {
    const { result } = renderHook(() => useToastStack());
    const arrived = vi.fn();
    window.addEventListener("chatterly:notif-arrived", arrived);
    act(() => deliverNotification(s, arrival()));
    window.removeEventListener("chatterly:notif-arrived", arrived);
    expect(readNotifHistory().deliver?.map((r) => [r.id, r.text])).toEqual([["d1", "<b>sent</b> you a $5 tip"]]);
    expect(result.current.map((t) => t.id)).toEqual(toasts ? ["d1"] : []);
    expect(arrived).toHaveBeenCalledTimes(toasts ? 1 : 0);
  });
});

describe("extract*FromHtml", () => {
  const html = '<a href="https://onlyfans.com/jim.b"><img class="a" src="https://x/av.jpg"></a> liked';
  it.each([
    [html, "https://x/av.jpg", "jim.b"],
    ['<a href="https://www.onlyfans.com/ann">', null, "ann"],
    ["no tags", null, null],
    [undefined, null, null],
  ])("%j", (raw, avatar, username) => {
    expect(extractAvatarFromHtml(raw)).toBe(avatar);
    expect(extractUsernameFromHtml(raw)).toBe(username);
  });
});

describe("toastArrival: who the toast is from", () => {
  const NOW = 9_000;
  const html = '<a href="https://onlyfans.com/htmluser"><img src="https://x/html.jpg"></a> liked your post';
  const related = { id: 11, name: "Rel", username: "rel", avatar: "rel.jpg", avatarThumbs: { c144: "rel144.jpg" } };
  const repl = {
    "{RELATED_USER_ID}": "22", "{RELATED_USER_NAME}": "Repl",
    "{RELATED_USER_LOGIN}": "repl", "{RELATED_USER_AVATAR}": "repl.jpg",
  };
  const from = { id: 33, name: "From", username: "from", avatar: "from.jpg" };
  const recipient = { id: 44, name: "Model", username: "model", avatar: "model.jpg" };
  const raw = (over: Record<string, unknown>) => ({ id: 7, type: "favorited", text: html, ...over });

  it.each([
    // [label, payload overrides, expected user]
    ["relatedUser beats all; c144 thumb beats avatar",
      { data: { relatedUser: related, replacements: repl }, fromUser: from, user: recipient },
      { id: 11, name: "Rel", username: "rel", avatar: "rel144.jpg" }],
    ["relatedUser c50 then avatar",
      { data: { relatedUser: { ...related, avatarThumbs: { c50: "rel50.jpg" } } } },
      { id: 11, name: "Rel", username: "rel", avatar: "rel50.jpg" }],
    ["replacements next (id parsed to a number)",
      { data: { replacements: repl }, fromUser: from, user: recipient },
      { id: 22, name: "Repl", username: "repl", avatar: "repl.jpg" }],
    ["a non-numeric replacement id falls through to fromUser's",
      { data: { replacements: { ...repl, "{RELATED_USER_ID}": "abc" } }, fromUser: from },
      { id: 33, name: "Repl", username: "repl", avatar: "repl.jpg" }],
    ["fromUser next",
      { fromUser: from, user: recipient },
      { id: 33, name: "From", username: "from", avatar: "from.jpg" }],
    ["HTML next for username/avatar; the recipient only for the name, never the id",
      { user: recipient },
      { id: undefined, name: "Model", username: "htmluser", avatar: "https://x/html.jpg" }],
    ["recipient's username when the HTML has none",
      { text: "liked", user: recipient },
      { id: undefined, name: "Model", username: "model", avatar: undefined }],
  ] as const)("%s", (_l, over, user) => {
    expect(toastArrival("acc", raw(over), NOW)?.user).toEqual(user);
  });

  it.each([
    [null], ["x"], [{ type: "tip" }], [{ id: null }],
  ])("%j has no id: null", (r) => {
    expect(toastArrival("acc", r, NOW)).toBeNull();
  });

  it("text falls back description → title, replacements render, createdAt falls back to now", () => {
    const a = toastArrival("acc", { id: 1, type: "tip", title: "{RELATED_USER_NAME} <b>tipped</b>", data: { replacements: repl } }, NOW)!;
    expect(a).toMatchObject({
      id: "1", accountId: "acc", typeKey: "tip", rawType: "tip", text: "Repl tipped",
      historyText: "{RELATED_USER_NAME} <b>tipped</b>", replacePairs: repl, createdMs: NOW,
    });
    expect(toastArrival("acc", { id: 1, description: "d", createdAt: "bad" }, NOW)).toMatchObject({ text: "d", createdMs: NOW, rawType: "" });
    expect(toastArrival("acc", { id: 1, text: "t", description: "d", createdAt: "2026-10-31T00:00:00Z" }, NOW))
      .toMatchObject({ text: "t", createdMs: Date.parse("2026-10-31T00:00:00Z") });
    // No replacements: the payload's own replacePairs.
    expect(toastArrival("acc", { id: 1, text: "{A}", replacePairs: { "{A}": "b" } }, NOW)).toMatchObject({ text: "b", replacePairs: { "{A}": "b" } });
  });

  it.each([
    ["tip", true], ["purchases", true], ["message", false], ["favorited", false],
  ])("%s deep-links with ?refresh=media: %s", (type, refresh) => {
    const a = toastArrival("acc", { id: 1, type, fromUser: from }, NOW)!;
    expect(a.href).toBe(notificationHref("acc", a.user, { refresh }));
    expect(a.href!.includes("refresh=media")).toBe(refresh);
  });
});

describe("dmArrival", () => {
  const target = (msg: Partial<ChatTarget["msg"]>): ChatTarget => ({
    accountId: "acc", fanId: 5, isOutbound: false, fromId: 5,
    msg: { id: 100, fromUser: { id: 5, name: "", username: "jim", avatar: "a.jpg" }, ...msg },
  });
  it.each([
    // [label, msg, text, historyText]
    ["text rendered", { text: " <p>hey</p> " }, "hey", "<p>hey</p>"],
    ["media only", { text: "", mediaCount: 2 }, "Sent you media", "Sent you media"],
    ["empty", {}, "Sent you a message", "Sent you a message"],
  ] as const)("%s", (_l, msg, text, historyText) => {
    const a = dmArrival(target(msg), 9_000);
    const user = { id: 5, name: "jim", username: "jim", avatar: "a.jpg" };
    expect(a).toEqual({
      id: "m100", accountId: "acc", typeKey: "message", rawType: "message",
      user, text, historyText, createdMs: 9_000, href: notificationHref("acc", user),
    });
    expect(a.href).not.toContain("refresh=media");
  });
});

describe("purchaseArrival", () => {
  it.each([
    // [label, payload extras, cached, name, text]
    ["names the payer; cents formatted", { amount_cents: 2522, name: "Jim" }, { name: "Cached", username: "jc" }, "Jim", "Unlocked your PPV — $25.22"],
    ["no name: the cache's", { amount_cents: 0 }, { name: "Cached", username: "jc" }, "Cached", "Unlocked your PPV"],
    ["nothing cached", { amount_cents: Number.NaN }, null, undefined, "Unlocked your PPV"],
  ] as const)("%s", (_l, extra, cached, name, text) => {
    const a = purchaseArrival("acc", { notif_id: "777", fan_id: 9, created_at: "2026-10-31T00:00:00+00:00", ...extra }, cached, 1);
    expect(a).toMatchObject({
      id: "777", accountId: "acc", typeKey: "purchases", rawType: "purchases", text,
      user: { id: 9, name, username: cached?.username }, createdMs: Date.parse("2026-10-31T00:00:00Z"),
    });
    expect(a.href).toContain("refresh=media");
  });
});
