"use client";

/**
 * Per-model identity for the OF mirror (public/of-mirror/pages, built
 * by scripts/of-mirror.mjs). The pages carry fixed placeholders; with a
 * single-model scope we swap in that model's live `/users/me` values after the
 * frame loads. Scope "all" or a failed fetch leaves the placeholders alone (Home's
 * price line, which only shows a real price, stays hidden then); My profile and the
 * avatar menu show the first model in "all" instead (standInModel, ofMirrorProfile).
 * The avatar menu's chevron lists the agency's models and switches scope: see bindSwitcher.
 */

import { useEffect, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { ofMeQuery, type OfMe } from "@/lib/ofMe";
import { proxyImage } from "@/lib/mediaUrl";
import { fillSlot, htmlLines } from "@/lib/ofMirrorData";

// `/users/me` lives in lib/ofMe (Messages Pro reads it too); re-exported for the mirror's readers.
export { ofMeQuery, type OfMe };

// Must match PLACEHOLDER / BIO in scripts/of-mirror.mjs; price: the generator's fake for a one-digit amount with cents.
const PH = { username: "yourmodel", name: "Your Model", bio: "Welcome to my page.", price: "$5.00" };

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);

/** A nav badge as OF shows it: nothing at zero, else the number, capped at "99+". */
const badge = (n: number) => (n > 99 ? "99+" : String(n));
/**
 * OF's one short count (its `formatCount`, bundle module 720548's B4), behind the sidebar's Fans / Following,
 * the profile's Photos / Videos / Likes / Fans and the lists column: by digit count, 999, "1.0K", "14.1K",
 * "1.23M", "12.3M" — OF's own rounding, so 999950 reads "1000.0K" there too.
 */
export function formatCount(n: number): string {
  const { length } = `${n}`;
  return length >= 8 ? `${(n / 1e6).toFixed(1)}M` : length >= 7 ? `${(n / 1e6).toFixed(2)}M` : length >= 4 ? `${(n / 1e3).toFixed(1)}K` : String(n);
}

/** The left nav's [data-oi-count] marks: the Creator's own counts; a field `me` lacks keeps the generator's blank. */
function applyNavCounts(doc: Document, me: OfMe): void {
  for (const el of doc.querySelectorAll<HTMLElement>("[data-oi-count]")) {
    const v = me[el.dataset.oiCount as keyof OfMe];
    if (typeof v !== "number" || !Number.isFinite(v)) continue;
    if (el.classList.contains("l-header__menu__item__count")) {
      el.textContent = v > 0 ? ` ${badge(v)} ` : "";
      el.style.display = v > 0 ? "" : "none";
    } else el.textContent = ` ${formatCount(Math.max(0, v))} `;
  }
}

/**
 * Bio as plain text: `rawAbout` as is, else `about`'s lines (htmlLines) joined by newlines: OF's editor shows them
 * (white-space: break-spaces) and counts them.
 */
export function bioOf(me: OfMe): string | null {
  if (typeof me.rawAbout === "string") return me.rawAbout;
  if (typeof me.about !== "string") return null;
  return htmlLines(me.about).join("\n");
}

// The mirror's own text and attributes before the first swap: a later apply (new values after a save) starts from them.
const origText = new WeakMap<Node, string>();
const origAttr = new WeakMap<Element, Map<string, string>>();
const origHtml = new WeakMap<Element, string>();

/** The avatar menu's rows OF draws from `/users/me` (its sidebar's rules); a flag `me` lacks keeps the capture's row. */
function applyDrawer(doc: Document, me: OfMe): void {
  const name = doc.querySelector<HTMLElement>(".l-sidebar__username .g-user-name");
  if (name && typeof me.isVerified === "boolean") {
    name.classList.toggle("m-verified", me.isVerified);
    name.querySelector<SVGElement>("svg")?.style.setProperty("display", me.isVerified ? "" : "none");
  }
  const dot = doc.querySelector<HTMLElement>(".l-sidebar__avatar .g-avatar__icon");
  if (dot && typeof me.isVisibleOnline === "boolean") dot.style.display = me.isVisibleOnline ? "" : "none";
  const bank = doc.querySelector<HTMLElement>(".l-sidebar__menu a[at-attr='bank']");
  if (bank && typeof me.canReceiveManualPayout === "boolean") {
    if (!origHtml.has(bank)) origHtml.set(bank, bank.innerHTML);
    bank.innerHTML = origHtml.get(bank)!;
    if (me.canReceiveManualPayout) {
      // OF's icon-bank and its bank item; the capture's model could not be paid out ("Add bank (to earn)").
      bank.querySelector("svg")?.setAttribute("data-icon-name", "icon-bank");
      for (const attr of ["href", "xlink:href"]) bank.querySelector("use")?.setAttribute(attr, "#icon-bank");
      const text = bank.querySelector(".l-sidebar__menu__text");
      if (text) text.innerHTML = 'Bank <span class="g-gray-text">(to earn)</span>';
    }
  }
}

/** Replace the mirror's placeholders in `doc` with `me`. Idempotent, and re-applies over earlier values; fields `me` lacks keep the placeholders. */
export function applyIdentity(doc: Document, me: OfMe, imageUrl: (url: string) => string = (u) => u): void {
  const username = str(me.username);
  const name = str(me.name);
  const bio = bioOf(me);
  const price = typeof me.subscribePrice === "number" ? me.subscribePrice : null;
  const priceText = price === null ? null : price === 0 ? "Free" : `$${price.toFixed(2)}`;

  const swap = (t: string) => {
    if (username) t = t.split(PH.username).join(username);
    if (name) t = t.split(PH.name).join(name);
    return t;
  };

  const walker = doc.createTreeWalker(doc.body, 4 /* NodeFilter.SHOW_TEXT */);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    let t = origText.get(n) ?? n.nodeValue ?? "";
    const trimmed = t.trim();
    if (bio !== null && trimmed === PH.bio) t = bio;
    else if (priceText && trimmed === PH.price && n.parentElement?.classList.contains("b-amount-price")) t = priceText;
    else {
      t = swap(t);
      if (name && /^\s*Y\s*$/.test(t) && n.parentElement?.classList.contains("m-text-avatar")) t = ` ${[...name][0]} `;
    }
    if (t !== n.nodeValue) {
      if (!origText.has(n)) origText.set(n, n.nodeValue ?? "");
      n.nodeValue = t;
    }
  }

  for (const input of doc.querySelectorAll<HTMLInputElement>("input")) {
    const v = input.id === "input-login" ? username : input.id === "input-name" ? name : null;
    if (v) {
      input.value = v;
      const counter = input.closest(".g-input__wrapper")?.querySelector(".v-counter");
      if (counter) counter.textContent = (counter.textContent ?? "").replace(/^\s*\d+/, String([...v].length));
    }
  }
  // Home's price line ([data-oi-price], the generator's) stays hidden until it shows the Creator's own price.
  if (priceText) for (const el of doc.querySelectorAll<HTMLElement>("[data-oi-price]")) el.style.removeProperty("display");
  if (price) {
    const priceInput = doc.querySelector<HTMLInputElement>("input[placeholder='Free']");
    if (priceInput) priceInput.value = String(price);
  }

  if (bio !== null) {
    for (const el of doc.querySelectorAll("[data-placeholder='Bio']")) {
      const counter = el.closest(".g-input__wrapper")?.querySelector(".count-block");
      if (counter) counter.textContent = (counter.textContent ?? "").replace(/\d+/, String([...bio].length));
    }
  }

  // Tooltips and accessible names (the avatar's alt, "Message @yourmodel").
  for (const el of doc.querySelectorAll("[title], [aria-label], [alt]")) {
    for (const attr of ["title", "aria-label", "alt"]) {
      const cur = el.getAttribute(attr);
      const v = origAttr.get(el)?.get(attr) ?? cur;
      if (v === null || swap(v) === cur) continue;
      if (!origAttr.has(el)) origAttr.set(el, new Map());
      if (!origAttr.get(el)!.has(attr)) origAttr.get(el)!.set(attr, cur!);
      el.setAttribute(attr, swap(v));
    }
  }
  applyNavCounts(doc, me);
  applyDrawer(doc, me);
  const header = str(me.header);
  if (header) doc.querySelector("img.b-profile__header__cover-img")?.setAttribute("src", imageUrl(header));
  const avatar = str(me.avatar);
  if (avatar) {
    // .of-fan: a fan's avatar (the generator marks them), which stays a placeholder.
    // A picture inside it: OF's placeholder paints its ::after over its own background.
    for (const ph of doc.querySelectorAll<HTMLElement>(".g-avatar__placeholder.m-text-avatar:not(.of-fan)")) {
      const pic = ph.querySelector<HTMLImageElement>("img[data-oi-avatar]") ?? doc.createElement("img");
      pic.setAttribute("data-oi-avatar", "");
      pic.alt = "";
      pic.src = imageUrl(avatar);
      pic.style.cssText = "width:100%;height:100%;object-fit:cover;border-radius:inherit;";
      if (!pic.isConnected) ph.replaceChildren(pic);
    }
    // Edit profile: OF's avatar has a remove button beside its camera once there is an avatar (disabled, as the
    // header's: its markup with the avatar's scoped-style attribute).
    const btns = doc.querySelector(".b-profile__user .g-avatar .b-profile__header__cover__btns");
    const close = doc.querySelector(".b-profile__header > .b-profile__header__cover__btns > button");
    if (btns && close && !btns.querySelector("[data-oi-avatar-remove]")) {
      const x = close.cloneNode(true) as Element;
      x.removeAttribute("data-v-234719ad");
      x.querySelector("svg")?.removeAttribute("data-v-234719ad");
      x.setAttribute("data-v-710dd05d", "");
      x.setAttribute("data-oi-avatar-remove", "");
      fillSlot(btns, "append", x);
    }
  }
}

/** One row of the avatar menu's account switcher. */
export interface SwitcherModel {
  id: string;
  name: string;
  username?: string | null;
  avatar?: string | null;
}

const SVG_NS = "http://www.w3.org/2000/svg";
const icon = (doc: Document, id: string, cls = "g-icon") => {
  const svg = doc.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const use = doc.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#${id}`);
  svg.append(use);
  return svg;
};
const el = (doc: Document, tag: string, cls: string, text?: string) => {
  const e = doc.createElement(tag);
  e.className = cls;
  if (text !== undefined) e.textContent = ` ${text} `;
  return e;
};

/** OF's connected-account row (its switcher's markup, 63420.css styles it): avatar, name, @handle, the current one ticked. */
function switcherRow(doc: Document, m: SwitcherModel, current: boolean, imageUrl: (url: string) => string): HTMLElement {
  const row = el(doc, "div", `connected-accounts${current ? " m-current" : ""}`);
  row.setAttribute("data-v-5d71f54a", "");
  const round = el(doc, "span", "connected-accounts__round");
  const avatar = el(doc, "span", "g-avatar m-w36");
  if (m.avatar) {
    const img = doc.createElement("img");
    img.alt = "";
    img.src = imageUrl(m.avatar);
    img.style.cssText = "width:36px;height:36px;object-fit:cover;border-radius:50%;";
    avatar.append(img);
  } else {
    // Not .m-text-avatar: applyIdentity paints those with the shown model's picture.
    const letter = el(doc, "span", "g-avatar__placeholder", [...m.name][0]?.toUpperCase() ?? "");
    letter.style.cssText = "display:flex;align-items:center;justify-content:center;width:36px;height:36px;font-size:16px;";
    avatar.append(letter);
  }
  round.append(avatar);
  const body = el(doc, "span", `connected-accounts__body${current ? " m-with-status" : ""}`);
  const nameRow = el(doc, "span", "b-username-row m-width-limit m-gap-clear");
  nameRow.append(el(doc, "span", "g-user-name", m.name));
  body.append(nameRow);
  if (m.username) {
    const handleRow = el(doc, "span", "b-username-row m-width-limit m-gap-clear");
    const wrap = el(doc, "span", "g-user-realname__wrapper m-nowrap-text");
    wrap.append(el(doc, "span", "g-user-username", `@${m.username}`));
    handleRow.append(wrap);
    body.append(handleRow);
  }
  row.append(round, body);
  if (current) {
    const tick = el(doc, "span", "connected-accounts__actions m-success");
    tick.append(icon(doc, "icon-done", "m-aligned-top g-icon"));
    row.append(tick);
  }
  return row;
}

/**
 * The avatar menu's chevron ([data-oi-switcher], the generator's): OF's account switcher over the agency's models.
 * It opens OF's menu under the chevron: one row per model, `current` ticked, then "Add another account" (the
 * app's /creators page, where a model is added). A pick calls `onPick` with the model's id (in All models the ticked one is the stand-in,
 * so picking it selects it); a pick, Escape or a click outside closes it. Returns the unbind.
 */
export function bindSwitcher(
  doc: Document,
  models: readonly SwitcherModel[],
  current: string | null,
  onPick: (accountId: string) => void,
  imageUrl: (url: string) => string = (u) => u,
): () => void {
  const wrap = doc.querySelector<HTMLElement>("[data-oi-switcher]");
  const toggle = wrap?.querySelector<HTMLButtonElement>("button");
  if (!wrap || !toggle) return () => {};
  toggle.setAttribute("data-oi-wired", "");
  let menu: HTMLElement | null = null;
  const close = () => {
    menu?.remove();
    menu = null;
    toggle.setAttribute("aria-expanded", "false");
    wrap.classList.remove("m-open");
  };
  const open = () => {
    const narrow = (doc.defaultView?.innerWidth ?? 1024) < 576;
    const width = narrow ? 320 : 344;
    menu = el(doc, "div", "v-menu__content theme--light menuable__content__active m-dropdown-v2 m-user-switcher");
    menu.setAttribute("role", "menu");
    menu.setAttribute("data-oi-switcher-menu", "");
    const list = el(doc, "div", "v-list m-dropdown-v-list v-sheet theme--light shown");
    const item = (tag: "button" | "a") => {
      const it = el(doc, tag, "m-with-rectangle-hover m-tb-sm v-list-item v-list-item--link theme--light");
      it.setAttribute("role", "menuitem");
      it.style.cssText = "width:100%;text-align:left;border:0;background:none;";
      return it;
    };
    for (const m of models) {
      const b = item("button");
      b.setAttribute("type", "button");
      b.setAttribute("data-oi-model", m.id);
      b.append(switcherRow(doc, m, m.id === current, imageUrl));
      b.addEventListener("click", () => {
        close();
        onPick(m.id);
      });
      list.append(b);
    }
    if (models.length) list.append(el(doc, "hr", "v-divider theme--light"));
    const add = item("a");
    add.setAttribute("href", "/creators");
    add.setAttribute("target", "_top");
    const addRow = el(doc, "div", "connected-accounts");
    addRow.setAttribute("data-v-5d71f54a", "");
    const plus = el(doc, "span", "connected-accounts__round");
    plus.append(icon(doc, "icon-add"));
    const addBody = el(doc, "span", "connected-accounts__body");
    addBody.append(el(doc, "span", "g-user-name", "Add another account"));
    addRow.append(plus, addBody);
    add.append(addRow);
    list.append(add);
    menu.append(list);
    const r = toggle.getBoundingClientRect();
    const vw = doc.defaultView?.innerWidth ?? width;
    const left = Math.max(8, Math.min(r.left - 3, vw - width - 8));
    menu.style.cssText = `position:fixed;top:${r.bottom + 4}px;left:${left}px;min-width:${width}px;max-width:${width}px;z-index:10000;`;
    doc.body.append(menu);
    toggle.setAttribute("aria-expanded", "true");
    wrap.classList.add("m-open");
  };
  const onToggle = (e: Event) => {
    e.preventDefault();
    e.stopPropagation();
    if (menu) close();
    else open();
  };
  const onOutside = (e: Event) => {
    if (menu && !menu.contains(e.target as Node) && !toggle.contains(e.target as Node)) close();
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") close();
  };
  toggle.addEventListener("click", onToggle);
  doc.addEventListener("mousedown", onOutside, true);
  doc.addEventListener("keydown", onKey);
  return () => {
    close();
    toggle.removeEventListener("click", onToggle);
    doc.removeEventListener("mousedown", onOutside, true);
    doc.removeEventListener("keydown", onKey);
  };
}

/** The switcher's rows: the agency's models (the scope picker's order), the shown one with its own name, handle and picture. */
export function switcherModels(accounts: readonly { id: string; nickname?: string | null; name?: string | null }[], current: string | null, me: OfMe | undefined): SwitcherModel[] {
  return accounts.map((a) => {
    const label = str(a.nickname) ?? str(a.name) ?? a.id;
    return a.id === current && me ? { id: a.id, name: str(me.name) ?? label, username: str(me.username), avatar: str(me.avatar) } : { id: a.id, name: label };
  });
}

/**
 * Single-model scope: fetch that model's `/users/me` and apply it to the frame
 * on every load (pages remount per route). Otherwise does nothing. Either way the
 * avatar menu's chevron lists the agency's models (bindSwitcher); a pick scopes to it.
 */
export function useOfIdentity(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId, setScope } = useScope();
  const { data: me } = useQuery(ofMeQuery(accountId));
  const accounts = useActiveAccounts();

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const models = switcherModels(accounts, accountId, me);
    let unbind = () => {};
    const bind = () => {
      unbind();
      const doc = frame.contentDocument;
      unbind = doc?.body
        ? bindSwitcher(doc, models, accountId, (id) => setScope({ kind: "model", accountId: id }), (u) => proxyImage(u, accountId))
        : () => {};
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind();
    };
  }, [frameRef, src, me, accountId, accounts, setScope]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !me || !accountId) return;
    const apply = () => {
      const doc = frame.contentDocument;
      if (doc?.body) applyIdentity(doc, me, (u) => proxyImage(u, accountId));
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => frame.removeEventListener("load", apply);
  }, [frameRef, src, me, accountId]);
}
