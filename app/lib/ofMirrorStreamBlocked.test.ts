import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { RelayError } from "@/lib/relay";
import {
  applyBlocked,
  bindStreamBlock,
  blockPath,
  BLOCKED_PAGE,
  ENTER_USERNAME,
  readBlocked,
  unblockPath,
  usernameOf,
  type BlockedUser,
} from "./ofMirrorStreamBlocked";


const fx = JSON.parse(readFileSync(resolve(__dirname, "__fixtures__/of/settings-stream-blocked.json"), "utf8")) as {
  pages: { path: string; body: { list: BlockedUser[]; hasMore: boolean } }[];
  rows: { name: string; username: string; verified: boolean }[];
};
const load = () => {
  document.documentElement.innerHTML = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${BLOCKED_PAGE}.html`), "utf8");
  return document;
};
const textOf = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
const form = () => document.querySelector("#content .b-settings__content form")!;
const rows = () => [...document.querySelectorAll<HTMLElement>(".b-rows-lists__item.m-control-right.m-roung-img-left")];

describe("Blocked users", () => {
  it("reads OF's pages of 10 until hasMore is false", async () => {
    const get = vi.fn((path: string) => Promise.resolve(fx.pages.find((p) => p.path === path)!.body));
    const users = await readBlocked(get);
    expect(get.mock.calls.map((c) => c[0])).toEqual(fx.pages.map((p) => p.path));
    expect(users.map((u) => u.id)).toEqual([700001, 700002, 700003]);
  });

  it("draws OF's rows under the form, the remove button disabled with the house tooltip", () => {
    const d = load();
    applyBlocked(d, fx.pages.flatMap((p) => p.body.list), (u) => `/img?u=${encodeURIComponent(u)}`, false);
    expect(form().classList.contains("g-border-bottom")).toBe(true);
    expect(form().nextElementSibling?.className).toBe("b-rows-lists b-menu-list g-border-bottom");
    expect(rows()).toHaveLength(fx.rows.length);
    rows().forEach((r, i) => {
      expect(textOf(r.querySelector(".g-user-name"))).toBe(fx.rows[i].name);
      expect(textOf(r.querySelector(".g-user-username"))).toBe(fx.rows[i].username);
      expect(!!r.querySelector(".g-user-name svg.m-verified")).toBe(fx.rows[i].verified);
      const remove = r.querySelector<HTMLButtonElement>("button.m-btn-remove")!;
      expect([remove.disabled, remove.title]).toEqual([true, "Not available in Inflowwww yet"]);
      expect(remove.querySelector("use")?.getAttribute("href")).toBe("#icon-close");
    });
    expect(rows()[0].querySelector("img")?.getAttribute("src")).toContain("/img?u=");
    expect((d.getElementById("input-365") as HTMLInputElement).disabled).toBe(true);
  });

  it("drawn again (a reload, another model): one list; none: no list, no text, no border", () => {
    const d = load();
    applyBlocked(d, fx.pages[0].body.list, undefined, false);
    applyBlocked(d, fx.pages[1].body.list, undefined, false);
    expect(rows()).toHaveLength(1);
    const before = textOf(d.querySelector("#content .b-settings__content"));
    applyBlocked(d, [], undefined, false);
    expect(rows()).toHaveLength(0);
    expect(form().classList.contains("g-border-bottom")).toBe(false);
    expect(textOf(d.querySelector("#content .b-settings__content"))).not.toBe(before);
    applyBlocked(d, undefined, undefined, false);
    expect(rows()).toHaveLength(0);
  });
});

describe("Block a username and a row's unblock (ticket 73)", () => {
  const input = () => document.getElementById("input-365") as HTMLInputElement;
  const blockBtn = () => form().querySelector<HTMLButtonElement>("button[type='submit']")!;
  const flush = () => new Promise((r) => setTimeout(r, 0));
  const confirmBtn = (text: string) =>
    [...document.querySelectorAll<HTMLButtonElement>("#ModalConfirm .modal-footer button")].find((b) => b.textContent?.trim() === text)!;
  const setup = (block = vi.fn(() => Promise.resolve({ success: true })), unblock = vi.fn(() => Promise.resolve({ success: true }))) => {
    const d = load();
    applyBlocked(d, fx.pages[0].body.list, undefined, true);
    const unbind = bindStreamBlock(d, { block, unblock });
    return { d, block, unblock, unbind };
  };

  it("paths and the typed name: OF's path segments, '@' dropped", () => {
    expect(blockPath("fan.one")).toBe("/api/of/v2/streams/users/fan.one/block");
    expect(unblockPath("700001")).toBe("/api/of/v2/streams/users/700001/block");
    expect(usernameOf("  @fan_1 ")).toBe("fan_1");
  });

  it("the form and each remove are Wired: enabled, Not-yet title kept", () => {
    setup();
    for (const el of [input(), blockBtn(), ...rows().map((r) => r.querySelector<HTMLButtonElement>("button.m-btn-remove")!)]) {
      expect([el.disabled, el.title, el.hasAttribute("data-oi-wired")]).toEqual([false, "Not available in Inflowwww yet", true]);
    }
  });

  it("Block sends the typed username once, clears the field and says saved", async () => {
    const { block } = setup();
    input().value = "@soakfan1";
    blockBtn().click();
    blockBtn().click();
    await flush();
    expect(block.mock.calls).toEqual([["soakfan1"]]);
    expect(input().value).toBe("");
    expect(document.getElementById("oi-toast")?.textContent).toContain("Changes were saved");
  });

  it("Enter in the field blocks too; an empty or impossible name sends nothing and says so", async () => {
    const { block } = setup();
    input().value = "a b";
    form().dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    expect(block).not.toHaveBeenCalled();
    expect(document.getElementById("oi-note")?.textContent).toBe(ENTER_USERNAME);
    input().value = "u900000000000100001";
    form().dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    expect(block.mock.calls).toEqual([["u900000000000100001"]]);
  });

  it("a failed Block (502) shows the red note and leaves the field and list as they were", async () => {
    const err = new RelayError(502, { detail: { upstream_status: 404, upstream_body: '{"error":{"message":"User not found"}}' } }, "502");
    const { block } = setup(vi.fn(() => Promise.reject(err)));
    const before = rows().length;
    input().value = "nosuchfan";
    blockBtn().click();
    await flush();
    await flush();
    expect(block).toHaveBeenCalledTimes(1);
    const n = document.getElementById("oi-note")!;
    expect(n.textContent).toMatch(/^Could not block: /);
    expect(n.style.color).toBe("rgb(255, 69, 69)");
    expect(input().value).toBe("nosuchfan");
    expect(rows()).toHaveLength(before);
    expect(blockBtn().disabled).toBe(false);
  });

  it("a row's remove asks first: Cancel sends nothing, Unblock sends that row's id", async () => {
    const { unblock } = setup();
    const remove = () => rows()[0].querySelector<HTMLButtonElement>("button.m-btn-remove")!;
    remove().click();
    await flush();
    confirmBtn("Cancel").click();
    await flush();
    expect(unblock).not.toHaveBeenCalled();
    remove().click();
    await flush();
    confirmBtn("Unblock").click();
    await flush();
    expect(unblock.mock.calls).toEqual([[String(fx.pages[0].body.list[0].id)]]);
  });

  it("a failed unblock shows the red note and keeps the row", async () => {
    const { unblock } = setup(undefined, vi.fn(() => Promise.reject(new Error("upstream 500"))));
    const remove = rows()[0].querySelector<HTMLButtonElement>("button.m-btn-remove")!;
    remove.click();
    await flush();
    confirmBtn("Unblock").click();
    await flush();
    await flush();
    expect(unblock).toHaveBeenCalledTimes(1);
    expect(document.getElementById("oi-note")?.textContent).toBe("Could not unblock: upstream 500");
    expect(rows()).toHaveLength(fx.pages[0].body.list.length);
    expect(remove.disabled).toBe(false);
  });

  it("unbound: clicks send nothing", async () => {
    const { block, unbind } = setup();
    unbind();
    input().value = "soakfan1";
    document.addEventListener("click", (e) => e.preventDefault(), { once: true });
    blockBtn().click();
    await flush();
    expect(block).not.toHaveBeenCalled();
  });
});
