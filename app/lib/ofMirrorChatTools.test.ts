import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addedLists,
  bindChatTools,
  chatToolWrites,
  COPIED,
  SAVED,
  type ChatToolsContext,
  type ChatToolWrites,
  type FanState,
} from "./ofMirrorChatTools";
import { discountShown, maxDiscount } from "./fanDiscount";
import { relatedOnly } from "./ofMirrorData";
import { frameNavigate } from "./ofMirrorPost";
import { ELSEWHERE } from "./ofMirrorTooltip";
import { NOT_YET, SELECT_MODEL } from "./ofMirrorWrites";
import { relay } from "./relay";

const page = (p: string) => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/messages/${p}.html`), "utf8");
  return document;
};
const fixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/${name}.json`), "utf8")) as T;
const users = fixture<Record<string, FanState>>("messages-users-list");
const FAN_ID = "2014"; // a subscriber in two of the Creator's lists
const FAN = users[FAN_ID];
const flush = () => new Promise((r) => setTimeout(r, 0));

const writes = (over: Partial<ChatToolWrites> = {}): ChatToolWrites & Record<string, ReturnType<typeof vi.fn>> =>
  ({
    rename: vi.fn(() => Promise.resolve({ id: 1 })),
    note: vi.fn(() => Promise.resolve({ id: 1 })),
    list: vi.fn(() => Promise.resolve({ success: true })),
    discount: vi.fn(() => Promise.resolve({ id: 1 })),
    restrict: vi.fn(() => Promise.resolve({ ok: true })),
    block: vi.fn(() => Promise.resolve({ success: true })),
    ...over,
  }) as never;
const ctx = (over: Partial<ChatToolsContext> = {}): ChatToolsContext => ({
  chat: FAN_ID,
  fan: FAN,
  info: { isMutedNotifications: false },
  me: { subscribePrice: 10, isPerformer: true },
  writes: writes(),
  back: `/of-manager/messages/chat?chat=${FAN_ID}`,
  navigate: vi.fn(),
  copy: vi.fn(() => Promise.resolve()),
  img: (u) => `/img?u=${u}`,
  ...over,
});
const tool = (d: Document, name: string) => d.querySelector<HTMLButtonElement>(`[data-oi-tool='${name}']`)!;
const item = (d: Document, key: string) => d.querySelector<HTMLElement>(`.of-state-menu [data-oi-menu='${key}']`)!;
const modal = (d: Document) => d.querySelector<HTMLElement>(".modal.show[role='dialog']")!;
const button = (d: Document, text: string) => [...modal(d).querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent!.trim() === text)!;
const text = (el: Element | null | undefined) => el?.textContent?.replace(/\s+/g, " ").trim();

const bound: (() => void)[] = [];
const bind = (...a: Parameters<typeof bindChatTools>) => {
  const u = bindChatTools(...a);
  bound.push(u);
  return u;
};
afterEach(() => {
  while (bound.length) bound.pop()!();
  vi.restoreAllMocks();
  document.getElementById("oi-toast")?.remove();
});

describe("the chat header's tools, from OF's user (/users/list)", () => {
  it("the star lights while the fan is in a list of the Creator's own (OF's addedLists), else OF's grey star-default", () => {
    expect(addedLists(FAN).map((l) => l.name)).toEqual(["Synth list 1", "Synth list 2"]);
    const d = page("chat");
    bind(d, "messages/chat", ctx());
    expect([tool(d, "lists").classList.contains("m-active"), tool(d, "lists").querySelector("svg")!.getAttribute("data-icon-name")]).toEqual([true, "icon-star-on"]);
    const plain = { ...FAN, listsStates: FAN.listsStates!.map((l) => (l.type === "custom" ? { ...l, hasUser: false } : l)) };
    const d2 = page("chat");
    bind(d2, "messages/chat", ctx({ fan: plain }));
    expect([tool(d2, "lists").classList.contains("m-gray"), tool(d2, "lists").querySelector("svg")!.getAttribute("data-icon-name"), tool(d2, "lists").getAttribute("aria-label")]).toEqual([true, "icon-star-default", "Add to lists"]);
  });

  it("the pencil, the notes icon and the bell follow OF's rules; none is disabled", () => {
    const d = page("chat");
    bind(d, "messages/chat", ctx({ fan: { ...FAN, notice: "vip" }, info: { isMutedNotifications: true } }));
    for (const t of ["rename", "lists", "notes"]) expect(tool(d, t).hasAttribute("disabled")).toBe(false);
    expect(tool(d, "notes").getAttribute("aria-label")).toBe("Edit notes");
    expect(d.querySelector("button[at-attr='mute_chat'] svg")!.getAttribute("data-icon-name")).toBe("icon-notification-off");
    const d2 = page("chat");
    bind(d2, "messages/chat", ctx({ fan: { ...FAN, subscribedOn: false, subscribedBy: false, subscribedOnExpiredNow: false, subscribedOnExpire: null, subscribedByExpire: null, subscribedIsExpiredNow: false } }));
    expect([tool(d2, "rename").style.display, tool(d2, "notes").style.display]).toEqual(["none", "none"]);
  });

  it("Rename user: the dialog opens on the custom name; Save sends it (the Relay's PUT …/custom-name) and says so; an error stays in the dialog", async () => {
    const d = page("chat");
    const w = writes({ rename: vi.fn().mockRejectedValueOnce(new Error("502 Bad Gateway")).mockResolvedValue({}) });
    bind(d, "messages/chat", ctx({ writes: w }));
    tool(d, "rename").click();
    expect(text(modal(d).querySelector(".modal-title"))).toBe("Rename user");
    const input = modal(d).querySelector<HTMLInputElement>("input")!;
    expect(input.value).toBe(FAN.displayName);
    input.value = "  Founder  ";
    button(d, "Save").click();
    await flush();
    expect(w.rename).toHaveBeenCalledWith("Founder");
    expect(text(modal(d).querySelector("[data-oi-error]"))).toBe("Could not save: 502 Bad Gateway");
    button(d, "Save").click();
    await flush();
    expect(modal(d)).toBeNull();
    expect(text(d.getElementById("oi-toast"))).toBe(SAVED);
  });

  it("Notes: Add notes / Edit notes; Save sends the text, an emptied note deletes it (\"\")", async () => {
    const d = page("chat");
    const w = writes();
    bind(d, "messages/chat", ctx({ writes: w, fan: { ...FAN, notice: "old" } }));
    tool(d, "notes").click();
    expect(text(modal(d).querySelector(".modal-title"))).toBe("Edit notes");
    const area = modal(d).querySelector<HTMLTextAreaElement>("textarea")!;
    expect(area.value).toBe("old");
    area.value = "";
    button(d, "Save").click();
    await flush();
    expect(w.note).toHaveBeenCalledWith("");
  });

  it("the lists dialog: a checkbox per list the fan is in or can join, OF's own lists fixed; a tick adds, an untick removes, an error ticks back", async () => {
    const d = page("chat");
    const w = writes({ list: vi.fn((id: string) => (id === "755017319" ? Promise.reject(new Error("400 Bad Request")) : Promise.resolve({}))) });
    bind(d, "messages/chat", ctx({ writes: w }));
    tool(d, "lists").click();
    expect(modal(d).hasAttribute("data-oi-wired")).toBe(true); // its checkboxes are this binder's, not the read-only fallback's
    const rows = [...modal(d).querySelectorAll<HTMLElement>("[data-oi-list]")];
    const want = FAN.listsStates!.filter((l) => l.hasUser || l.canAddUser);
    expect(rows.map((r) => r.dataset.oiList)).toEqual(want.map((l) => String(l.id)));
    const box = (id: string) => modal(d).querySelector<HTMLInputElement>(`[data-oi-list='${id}'] input`)!;
    expect(box("fans").disabled).toBe(true);
    expect(box("1320999428").checked).toBe(true);
    box("1320999428").click();
    expect(w.list).toHaveBeenLastCalledWith("1320999428", false);
    box("755017382").click();
    expect(w.list).toHaveBeenLastCalledWith("755017382", true);
    // A write refreshes the fan, which binds again: the dialog stays open.
    bind(d, "messages/chat", ctx({ writes: w, fan: { ...FAN, listsStates: FAN.listsStates!.map((l) => (String(l.id) === "755017382" ? { ...l, hasUser: true } : l)) } }));
    expect(modal(d)).not.toBeNull();
    box("755017319").click();
    await flush();
    expect(box("755017319").checked).toBe(false);
    expect(text(modal(d).querySelector("[data-oi-error]"))).toBe("Could not add to Bookmarks: 400 Bad Request");
  });

  it("All models (no model): a tool sends nothing and says to pick one", () => {
    const d = page("chat");
    bind(d, "messages/chat", ctx({ writes: null }));
    tool(d, "rename").click();
    expect(modal(d)).toBeNull();
    expect(d.getElementById("oi-note")!.textContent).toBe(SELECT_MODEL);
  });
});

describe("the chat's ⋮ menu (messages/chat/state-header-menu): OF's items for this fan", () => {
  const menu = (over: Partial<ChatToolsContext> = {}) => {
    const d = page("chat/state-header-menu");
    const c = ctx(over);
    const unbind = bind(d, "messages/chat/state-header-menu", c);
    return { d, c, unbind };
  };

  it("OF's order and labels; Restrict / Unrestrict @user and Block / Unblock by state; Purchases disabled, pointing at Messages Pro; the fan's own row", () => {
    const { d } = menu({ fan: { ...FAN, isRestricted: true }, info: { isMutedNotifications: false, hasPurchasedFeed: true } });
    const shown = [...d.querySelectorAll<HTMLElement>(".of-state-menu [data-oi-menu]")].filter((e) => e.style.display !== "none").map((e) => text(e));
    expect(shown).toEqual(["Copy link to profile", "Rename user", "Add to / remove from lists", "Give user a discount", "View user's comments", "Purchases", "Hide chat", "Unmute notifications", `Unrestrict @${FAN.username}`, "Block", "Report"]);
    expect(item(d, "purchases").title).toBe(ELSEWHERE.fanPurchases);
    const own = d.querySelector<HTMLAnchorElement>(".of-state-menu a.m-user-data-item")!;
    expect([text(own.querySelector(".g-user-username")), own.getAttribute("href")]).toEqual([`@${FAN.username}`, `https://onlyfans.com/${FAN.username}`]);
    const blocked = menu({ fan: { ...FAN, isBlocked: true } }).d;
    expect([text(item(blocked, "block")), item(blocked, "restrict").style.display, item(blocked, "discount").style.display]).toEqual(["Unblock", "none", "none"]);
  });

  it("Give user a discount only when OF offers it: a priced account whose discount stays above OF's floor, for a (past) subscriber", () => {
    expect(maxDiscount(10)).toBe(50);
    expect(maxDiscount(100)).toBe(60);
    expect(discountShown(FAN, 10)).toBe(true);
    expect(discountShown(FAN, 0)).toBe(false);
    expect(discountShown(FAN, 5)).toBe(false);
    expect(discountShown({ ...FAN, subscribedOn: false, subscribedOnExpiredNow: false, subscribedOnExpire: null }, 10)).toBe(false);
  });

  it("Copy link to profile: the profile's link to the clipboard, back to the chat, OF's toast there", async () => {
    window.history.replaceState({}, "", "/of-mirror/pages/messages/chat/state-header-menu.html");
    const push = vi.fn();
    const { d, c, unbind } = menu({ navigate: vi.fn(frameNavigate({ current: { contentDocument: document } as HTMLIFrameElement }, push)) });
    item(d, "copy").click();
    await flush();
    expect(c.copy).toHaveBeenCalledWith(`https://onlyfans.com/${FAN.username}`);
    expect(c.navigate).toHaveBeenCalledWith(c.back, COPIED);
    expect(push).toHaveBeenCalledWith(c.back);
    expect(d.getElementById("oi-toast")).toBeNull();
    unbind();
    // A bind while the frame still shows the menu page it left (a rebind on a fan refresh), or about:blank, leaves the
    // toast for the chat page.
    bind(page("chat/state-header-menu"), "messages/chat/state-header-menu", ctx());
    expect(document.getElementById("oi-toast")).toBeNull();
    window.history.replaceState({}, "", "/");
    const blank = page("chat");
    bind(blank, "messages/chat", ctx());
    expect(blank.getElementById("oi-toast")).toBeNull();
    window.history.replaceState({}, "", "/of-mirror/pages/messages/chat.html");
    const chat = page("chat");
    bind(chat, "messages/chat", ctx());
    expect(text(chat.getElementById("oi-toast"))).toBe(COPIED);
    // Shown once: the next bind of the chat page has none.
    chat.getElementById("oi-toast")!.remove();
    bind(page("chat"), "messages/chat", ctx());
    expect(document.getElementById("oi-toast")).toBeNull();
    window.history.replaceState({}, "", "/");
  });

  it("a dialog done on the chat page itself toasts there and carries nothing to a later chat page", async () => {
    window.history.replaceState({}, "", "/of-mirror/pages/messages/chat.html");
    const d = page("chat");
    const c = ctx();
    bind(d, "messages/chat", c);
    tool(d, "rename").click();
    button(d, "Save").click();
    await flush();
    expect(text(d.getElementById("oi-toast"))).toBe(SAVED);
    expect(c.navigate).not.toHaveBeenCalled();
    d.getElementById("oi-toast")!.remove();
    bind(page("chat"), "messages/chat", ctx());
    expect(document.getElementById("oi-toast")).toBeNull();
    window.history.replaceState({}, "", "/");
  });

  it("View user's comments: the commented notifications for this fan", () => {
    const { d, c } = menu();
    item(d, "comments").click();
    expect(c.navigate).toHaveBeenCalledWith(`/of-manager/notifications/commented?related_user=${FAN_ID}`);
    const rows = [{ user: { id: Number(FAN_ID) } }, { user: { id: 1 } }, { fromUser: { id: Number(FAN_ID) } }] as never[];
    expect(relatedOnly(rows, FAN_ID)).toHaveLength(2);
    expect(relatedOnly(rows, null)).toHaveLength(3);
  });

  it("Rename user from the menu: the menu closes, the dialog opens over the chat; Cancel goes back to the chat", () => {
    const { d, c } = menu();
    item(d, "rename").click();
    expect(d.querySelector<HTMLElement>(".of-state-menu")!.style.display).toBe("none");
    expect(text(modal(d).querySelector(".modal-title"))).toBe("Rename user");
    button(d, "Cancel").click();
    expect(c.navigate).toHaveBeenCalledWith(c.back, undefined);
  });

  it("Give user a discount: OF's percents (5 to the top, by 5), 1-12 months, the price it makes; Apply sends {discount, period}; Clear only with one set", async () => {
    const { d, c } = menu();
    item(d, "discount").click();
    const [pct, period] = [...modal(d).querySelectorAll<HTMLSelectElement>("select")];
    expect([...pct.options].map((o) => Number(o.value))).toEqual([5, 10, 15, 20, 25, 30, 35, 40, 45, 50]);
    expect(period.options).toHaveLength(12);
    expect(button(d, "Clear").disabled).toBe(true);
    expect([...modal(d).querySelectorAll<HTMLButtonElement>(".b-tabs__nav__link")].map((b) => [text(b), b.disabled])).toEqual([["Discount", false], ["Free trial", true]]);
    pct.value = "20";
    pct.dispatchEvent(new Event("change"));
    period.value = "3";
    period.dispatchEvent(new Event("change"));
    expect(text(modal(d).querySelector(".g-input__help"))).toBe("$8.00 per month for 3 months");
    button(d, "Apply").click();
    await flush();
    expect(c.writes!.discount).toHaveBeenCalledWith(20, 3);
    expect(c.navigate).toHaveBeenCalledWith(c.back, "Discount applied");
    const set = menu({ fan: { ...FAN, subscribedOnData: { discountPercent: 15, discountPeriod: 2 } } });
    item(set.d, "discount").click();
    expect(button(set.d, "Clear").disabled).toBe(false);
    button(set.d, "Clear").click();
    await flush();
    expect(set.c.writes!.discount).toHaveBeenCalledWith(0, 1);
    // An off-list current discount (13%, set elsewhere) shows as it is, but Apply waits for one OF offers.
    const odd = menu({ fan: { ...FAN, subscribedOnData: { discountPercent: 13, discountPeriod: 1 } } });
    item(odd.d, "discount").click();
    const sel = modal(odd.d).querySelector<HTMLSelectElement>("select")!;
    expect([sel.value, text(sel.selectedOptions[0]), sel.options[0].disabled, button(odd.d, "Apply").disabled]).toEqual(["13", "13% discount (current)", true, true]);
    sel.value = "10";
    sel.dispatchEvent(new Event("change"));
    expect(button(odd.d, "Apply").disabled).toBe(false);
  });

  it("Restrict: at once; Block asks first, Unblock at once; an error stays in place", async () => {
    const { d, c } = menu();
    item(d, "restrict").click();
    expect(c.writes!.restrict).toHaveBeenCalledWith(true);
    item(d, "block").click();
    expect(c.writes!.block).not.toHaveBeenCalled();
    expect(text(modal(d).querySelector(".modal-title"))).toBe("Block user");
    button(d, "Block").click();
    await flush();
    expect(c.writes!.block).toHaveBeenCalledWith(true);
    const un = menu({ fan: { ...FAN, isBlocked: true, isRestricted: false } });
    item(un.d, "block").click();
    expect(un.c.writes!.block).toHaveBeenCalledWith(false);
    const bad = menu({ writes: writes({ restrict: vi.fn(() => Promise.reject(new Error("403 Forbidden"))) }) });
    item(bad.d, "restrict").click();
    await flush();
    expect(bad.d.getElementById("oi-note")!.textContent).toBe("Could not restrict: 403 Forbidden");
  });

  it("Report is disabled (OF's form sends captcha data the mirror cannot fill): NOT_YET, no link, and a click sends nothing", async () => {
    const relayPost = vi.spyOn(relay, "post");
    const { d, c } = menu();
    const r = item(d, "report");
    expect([r.getAttribute("aria-disabled"), r.title, r.classList.contains("v-list-item--disabled"), r.querySelector("a.of-state-link")]).toEqual(["true", NOT_YET, true, null]);
    r.click();
    await flush();
    expect(modal(d)).toBeNull();
    expect(c.navigate).not.toHaveBeenCalled();
    expect(Object.values(c.writes!).every((f) => (f as ReturnType<typeof vi.fn>).mock.calls.length === 0)).toBe(true);
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("Hide chat and Mute stay ofMirrorChat's (this binder leaves them alone)", () => {
    const { d, c } = menu();
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
    item(d, "hide").dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
    expect(c.navigate).not.toHaveBeenCalled();
  });
});

describe("chatToolWrites: the exact Relay requests", () => {
  it("rename, notes, lists, discount, restrict (no '.' sent, no hide, unrestrict does not unhide), block", async () => {
    const qc = new QueryClient();
    const put = vi.spyOn(relay, "put").mockResolvedValue({});
    const post = vi.spyOn(relay, "post").mockResolvedValue({});
    const del = vi.spyOn(relay, "delete").mockResolvedValue({});
    const w = chatToolWrites("acc", "800000002", qc);
    const o = { accountId: "acc" };
    expect(Object.keys(w).sort()).toEqual(["block", "discount", "list", "note", "rename", "restrict"]); // no report write
    await w.rename("Founder");
    await w.note("");
    await w.list("1320999428", true);
    await w.list("1320999428", false);
    await w.discount(20, 3);
    await w.restrict(true);
    await w.restrict(false);
    await w.block(true);
    await w.block(false);
    expect(put.mock.calls).toEqual([
      ["/api/of/v2/subscriptions/800000002/custom-name", { name: "Founder" }, o],
      ["/api/of/v2/subscriptions/800000002/note", { note: "" }, o],
      ["/api/of/v2/subscriptions/800000002/discount", { discount: 20, period: 3 }, o],
    ]);
    expect(post.mock.calls).toEqual([
      ["/api/of/v2/lists/1320999428/users/800000002", undefined, o],
      ["/api/of/v2/users/800000002/restrict?ack=false&hide=false", undefined, o],
      ["/api/of/v2/users/800000002/block", undefined, o],
    ]);
    expect(del.mock.calls).toEqual([
      ["/api/of/v2/lists/1320999428/users/800000002", o],
      ["/api/of/v2/users/800000002/restrict?unhide=false", o],
      ["/api/of/v2/users/800000002/block", o],
    ]);
  });
});
