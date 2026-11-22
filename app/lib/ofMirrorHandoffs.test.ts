import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { asHandoff, bindHandoffs, HANDOFF_TITLE, HANDOFFS, handoffsFor, reportHandoffUrl } from "./ofMirrorHandoffs";
import { NOT_YET } from "./ofMirrorWrites";

const page = (p: string) => {
  const html = readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
  return new DOMParser().parseFromString(html, "text/html");
};
const anchor = (d: Document, text: string) =>
  [...d.querySelectorAll<HTMLAnchorElement>("#content a")].find((a) => a.textContent?.trim() === text)!;
const control = (d: Document, text: string) =>
  [...d.querySelectorAll<HTMLElement>("#content a, #content button")].find((a) => a.textContent?.trim() === text)!;
const SPOTIFY = "https://onlyfans.com/my/settings/spotify";
const BUTTONS = ["settings/account/google", "settings/account/x", "settings/account/connected"];

describe("HANDOFFS", () => {
  it.each([
    ["settings--ethwallet-metamask", "settings/ethwallet", "https://metamask.io/download.html"],
    ["settings--streaming-obs", "settings/streaming", "https://obsproject.com/download"],
    ["settings--streaming-chat-link", "settings/streaming", "https://onlyfans.com/my/streaming/chat"],
    ["settings--streaming-obs-widgets", "settings/streaming", "https://obs-settings.onlyfans.com/"],
    // ticket 58 r10: OF's own pages (measured), Spotify's settings page (inferred) on every page it shows.
    ["settings--account-google-sign-in", "settings/account/google", "https://onlyfans.com/my/settings/account/google"],
    ["settings--account-x-sign-in", "settings/account/x", "https://onlyfans.com/my/settings/account/x"],
    ["settings--account-connected-connect", "settings/account/connected", "https://onlyfans.com/my/settings/account/connected"],
    ["settings--spotify-sign-in", "settings/spotify", SPOTIFY],
    ["profile--spotify-sign-in", "profile/index", SPOTIFY],
    ["profile--media-spotify-sign-in", "profile/media", SPOTIFY],
    ["profile--state-more-menu-spotify-sign-in", "profile/state-more-menu", SPOTIFY],
  ])("%s on %s opens %s", (key, p, url) => {
    const h = HANDOFFS.find((e) => e.key === key)!;
    expect(h).toMatchObject({ page: p, url });
    expect(new URL(h.url).protocol).toBe("https:");
  });

  it("marks live exactly the entries whose Live proofs passed (D1); Connected accounts' field, not its Connect", () => {
    expect(HANDOFFS.filter((h) => h.live).map((h) => h.key)).toEqual([
      "settings--streaming-obs", "settings--streaming-chat-link", "settings--streaming-obs-widgets",
      "settings--account-google-sign-in", "settings--account-x-sign-in",
      "settings--spotify-sign-in", "profile--spotify-sign-in", "profile--media-spotify-sign-in",
      "profile--state-more-menu-spotify-sign-in",
    ]);
    expect(HANDOFFS.filter((h) => h.fieldLive).map((h) => h.key)).toEqual(["settings--account-connected-connect"]);
  });

  it("holds exactly those entries, keys unique, every URL https", () => {
    expect(HANDOFFS).toHaveLength(11);
    expect(new Set(HANDOFFS.map((h) => h.key)).size).toBe(11);
    for (const h of HANDOFFS) expect(h.url.startsWith("https://")).toBe(true);
  });

  it("never sends OF's trust call or a csrf: no URL carries a query, a /trust or a proxy path", () => {
    for (const h of HANDOFFS) {
      const u = new URL(h.url);
      expect(u.search, h.key).toBe("");
      expect(u.pathname, h.key).not.toMatch(/trust|proxy|auth/);
    }
  });

  it("each entry's control is on its committed page, scrubbed or disabled", () => {
    for (const h of HANDOFFS) {
      const c = control(page(h.page), h.text);
      expect(c, h.key).toBeTruthy();
      if (c.tagName === "A") {
        expect(c.getAttribute("href")).toBe("#");
        expect(c.title).toBe(NOT_YET);
      } else expect((c as HTMLButtonElement).disabled, h.key).toBe(true);
    }
  });
});

describe("bindHandoffs", () => {
  it.each(["settings/ethwallet", "settings/streaming", "settings/spotify", "profile/index", "profile/media", "profile/state-more-menu"])("wires %s's anchors to a new tab, title kept until its Live pass, and undoes", (p) => {
    const d = page(p);
    const undo = bindHandoffs(d, p);
    for (const h of handoffsFor(p)) {
      const a = anchor(d, h.text);
      expect(a.getAttribute("href")).toBe(h.url);
      expect(a.target).toBe("_blank");
      expect(a.rel).toBe("noopener noreferrer");
      expect(a.hasAttribute("data-oi-wired")).toBe(true);
      expect(a.hasAttribute("aria-disabled")).toBe(false);
      // D1: a `live` entry (its Live proof passed) drops the Not-yet title; the rest keep it.
      if (h.live) expect(a.hasAttribute("title"), h.key).toBe(false);
      else expect(a.title, h.key).toBe(NOT_YET);
    }
    undo();
    for (const h of handoffsFor(p)) {
      const a = anchor(d, h.text);
      expect(a.getAttribute("href")).toBe("#");
      expect(a.hasAttribute("data-oi-wired")).toBe(false);
      expect(a.getAttribute("aria-disabled")).toBe("true");
      expect(a.title).toBe(NOT_YET);
    }
  });

  it.each(BUTTONS)("swaps %s's disabled button for a Wired new-tab anchor, title kept until its Live pass, and undoes", (p) => {
    const d = page(p);
    const [h] = handoffsFor(p);
    const before = control(d, h.text) as HTMLButtonElement;
    const undo = bindHandoffs(d, p);
    const a = control(d, h.text) as HTMLAnchorElement;
    expect(a.tagName).toBe("A");
    expect(a.getAttribute("href")).toBe(h.url);
    expect(a.target).toBe("_blank");
    expect(a.rel).toBe("noopener noreferrer");
    expect(a.hasAttribute("data-oi-wired")).toBe(true);
    expect(a.className).toBe(before.className);
    if (h.live) expect(a.hasAttribute("title")).toBe(false);
    else expect(a.title).toBe(NOT_YET);
    expect(a.hasAttribute("disabled")).toBe(false);
    undo();
    expect(control(d, h.text)).toBe(before);
    expect(before.disabled).toBe(true);
    expect(d.querySelector("#content [data-oi-wired]")).toBeNull();
  });

  it("Connected accounts' username field is readonly, Wired, and a click on it opens Connect's hand-off", () => {
    const p = "settings/account/connected";
    const d = page(p);
    const undo = bindHandoffs(d, p);
    const field = d.querySelector<HTMLInputElement>("#settings_connect_account")!;
    // D1: the field's Live proof passed (title dropped); Connect's is parked (title kept).
    expect([field.disabled, field.readOnly, field.hasAttribute("data-oi-wired"), field.hasAttribute("title")]).toEqual([false, true, true, false]);
    const a = control(d, "Connect") as HTMLAnchorElement;
    expect(a.title).toBe(NOT_YET);
    const clicks: string[] = [];
    a.addEventListener("click", (e) => {
      e.preventDefault(); // jsdom does not navigate; the click reaching the anchor is the hand-off
      clicks.push(a.href);
    });
    field.click();
    (field.closest(".v-input")!.querySelector("label") as HTMLElement).click();
    expect(clicks).toEqual(["https://onlyfans.com/my/settings/account/connected", "https://onlyfans.com/my/settings/account/connected"]);
    undo();
    expect([field.disabled, field.readOnly, field.hasAttribute("data-oi-wired"), field.title]).toEqual([true, false, false, NOT_YET]);
    field.click();
    expect(clicks).toHaveLength(2);
  });

  it("leaves parked controls alone: Spring's here, NFT Connect, pages without entries", () => {
    const spring = page("settings/spring-store");
    bindHandoffs(spring, "settings/spring-store");
    expect(anchor(spring, "here").getAttribute("href")).toBe("#");
    const nft = page("settings/nft");
    bindHandoffs(nft, "settings/nft");
    const connect = nft.querySelector<HTMLButtonElement>("#content button.m-opensea")!;
    expect(connect.disabled).toBe(true);
    expect(nft.querySelector("#content [data-oi-wired]")).toBeNull();
    for (const p of ["settings/account", "settings/security", "settings/social-media"]) {
      const d = page(p);
      expect(bindHandoffs(d, p)).toBeTypeOf("function");
      expect(d.querySelector("#content [data-oi-wired]"), p).toBeNull();
    }
  });
});

// ticket 42: the three Reports' hand-offs (D22), from a fixture post (ofMirrorHome.test's another creator's post 11 by
// @deltafour) and chat (fan 2014, ofMirrorChatTools.test's).
describe("reportHandoffUrl", () => {
  it.each([
    ["post", reportHandoffUrl("post", { postId: 11, username: "deltafour" }), "https://onlyfans.com/11/deltafour", "/11/deltafour"],
    ["chat", reportHandoffUrl("chat", { fanId: "2014" }), "https://onlyfans.com/my/chats/chat/2014/", "/my/chats/chat/2014/"],
    ["message", reportHandoffUrl("message", { fanId: 2014 }), "https://onlyfans.com/my/chats/chat/2014/", "/my/chats/chat/2014/"],
  ])("Report on a %s opens %s", (_place, got, want, path) => {
    expect(got).toBe(want);
    const u = new URL(got);
    expect([u.protocol, u.host, u.pathname, u.search, u.hash]).toEqual(["https:", "onlyfans.com", path, "", ""]);
  });

  it("escapes its ids, so a handle never leaves the path", () => {
    expect(reportHandoffUrl("post", { postId: "7", username: "a/b?c" })).toBe("https://onlyfans.com/7/a%2Fb%3Fc");
  });

  it("asHandoff: an anchor in place; any other element swapped for one (its attributes but `drop`, its content); a new tab, noopener noreferrer, Wired, not disabled; the title is the caller's", () => {
    const a = document.createElement("a");
    a.setAttribute("aria-disabled", "true");
    a.title = "kept";
    document.body.append(a);
    expect(asHandoff(a, "https://onlyfans.com/my/chats/chat/2014/")).toBe(a);
    expect([a.href, a.target, a.rel, a.hasAttribute("data-oi-wired"), a.getAttribute("aria-disabled"), a.title])
      .toEqual(["https://onlyfans.com/my/chats/chat/2014/", "_blank", "noopener noreferrer", true, null, "kept"]);
    const div = document.createElement("div");
    div.className = "v-list-item";
    div.setAttribute("data-oi-menu", "report");
    div.setAttribute("aria-disabled", "true");
    div.setAttribute("data-drop", "x");
    div.textContent = " Report ";
    document.body.append(div);
    const b = asHandoff(div, "https://onlyfans.com/11/deltafour", ["data-drop"]);
    expect([b.tagName, b.isConnected, div.isConnected, b.className, b.dataset.oiMenu, b.hasAttribute("data-drop"), b.textContent, b.href, b.getAttribute("aria-disabled"), b.title])
      .toEqual(["A", true, false, "v-list-item", "report", false, " Report ", "https://onlyfans.com/11/deltafour", null, ""]);
    expect(HANDOFF_TITLE).toBe("opens onlyfans.com");
    a.remove();
    b.remove();
  });
});
