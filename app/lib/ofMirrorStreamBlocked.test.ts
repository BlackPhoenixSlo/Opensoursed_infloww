import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { applyBlocked, BLOCKED_PAGE, readBlocked, type BlockedUser } from "./ofMirrorStreamBlocked";

/** Settings > Streaming > Blocked users: OF's GET pages, its rows, the remove button disabled, no write. */

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
    applyBlocked(d, fx.pages.flatMap((p) => p.body.list), (u) => `/img?u=${encodeURIComponent(u)}`);
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
    // The block form stays disabled.
    expect((d.getElementById("input-365") as HTMLInputElement).disabled).toBe(true);
  });

  it("drawn again (a reload, another model): one list; none: no list, no text, no border", () => {
    const d = load();
    applyBlocked(d, fx.pages[0].body.list);
    applyBlocked(d, fx.pages[1].body.list);
    expect(rows()).toHaveLength(1);
    const before = textOf(d.querySelector("#content .b-settings__content"));
    applyBlocked(d, []);
    expect(rows()).toHaveLength(0);
    expect(form().classList.contains("g-border-bottom")).toBe(false);
    expect(textOf(d.querySelector("#content .b-settings__content"))).not.toBe(before);
    applyBlocked(d, undefined);
    expect(rows()).toHaveLength(0);
  });
});
