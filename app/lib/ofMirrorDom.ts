"use client";

/**
 * The OF mirror's DOM primitives, cut from ofMirrorData (which re-exports them): the undo list every change registers
 * with (track, restore, ...), cloning and filling rows (make, fill, fillGrid), users' names, links and avatars, OF's
 * date formats, icons and vault tiles, OF's infinite loading row (applyMore). Every ofMirrorData* and ofMirrorFeeds*
 * leaf imports them from here.
 */

import type { OFUserMini } from "@/lib/relay";
import { clockTime } from "@/lib/format";
import { undoList } from "@/lib/ofMirrorUndo";
import { initials } from "@/lib/ofMirrorAvatar";

export type Part = "chats" | "chatList" | "thread" | "gallery" | "vaultLists" | "vaultMedia" | "userLists" | "listRow" | "listUsers" | "listPosts" | "subscribers" | "labels" | "posts" | "profileMedia" | "bookmarks" | "queue" | "notifications" | "transactions" | "payouts" | "referrals"
  | "home" | "stories" | "notificationCounts" | "pastStreams" | "promotions" | "events" | "profile";

// Every change to the page's own nodes registers its undo (ofMirrorUndo); clones are just removed. Text is tracked even
// when it is the same (restore puts it back over a later change). `own`: a binder's rows on a page whose data
// restore re-runs, e.g. Home's tag dialog over the Home feed.
export const { track, own, setAttr, setClass, setText, restore } = undoList({ attrMode: "single", classUndo: "snapshot", skipEqualText: false });
/** Drop the classes `cls` from `el`. */
export function dropClass(doc: Document, el: Element, ...cls: string[]) {
  setAttr(doc, el, "class", [...el.classList].filter((c) => !cls.includes(c)).join(" "));
}

/** A copy of `tpl` without the markers useOfRow leaves on the page's own nodes. */
export function make(tpl: Element): HTMLElement {
  const c = tpl.cloneNode(true) as HTMLElement;
  for (const el of [c, ...c.querySelectorAll<HTMLElement>("*")]) {
    for (const a of [...el.attributes]) if (a.name.startsWith("data-oi-")) el.removeAttribute(a.name);
  }
  c.dataset.oiData = "";
  return c;
}

/**
 * Hide `examples`; append `clones` to `parents` in turn (default: the first
 * example's parent: trailing built-in rows can sit outside the list's virtual
 * scroller). A virtual scroller's absolutely placed item views become plain
 * flow, and its wrapper loses the examples' fixed height.
 */
export function fill(doc: Document, examples: HTMLElement[], clones: HTMLElement[], parents?: Element[]) {
  for (const e of examples) setAttr(doc, e, "style", `${e.getAttribute("style") ?? ""};display:none`);
  const targets = parents?.length ? parents : [examples[0].parentElement!];
  clones.forEach((c, i) => {
    if (c.classList.contains("vue-recycle-scroller__item-view")) {
      c.style.position = "relative";
      c.style.transform = "none";
    }
    targets[i % targets.length].appendChild(c);
    track(doc, () => c.remove());
  });
  for (const p of targets) if (p.classList.contains("vue-recycle-scroller__item-wrapper")) setAttr(doc, p, "style", null);
}

export const unit = (el: Element) => el.closest<HTMLElement>(".vue-recycle-scroller__item-view") ?? (el as HTMLElement);
export const nameOf = (u: OFUserMini | null | undefined) => u?.name?.trim() || u?.username || (u ? String(u.id) : "");
export const handleOf = (u: OFUserMini) => u.username || `u${u.id}`;
/**
 * Where a user's name and avatar go: the Creator's own (`me`, their id) My profile, anyone else's OF profile,
 * https://onlyfans.com/<handle> (by `u<id>` without one; the mirror has no other user's profile, as the chat list's
 * avatar); none for a user with neither id nor handle.
 */
export function userHref(u: { id?: unknown; username?: string | null } | null | undefined, me?: string | null): string | null {
  const id = u?.id == null || u.id === "" ? null : String(u.id);
  if (id == null && !u?.username) return null;
  if (me != null && id === me) return "/of-manager/profile";
  return `https://onlyfans.com/${encodeURIComponent(u?.username || `u${id}`)}`;
}
/** Point the cloned row's user links `links` at `href` (none: they stay as captured): My profile in the frame's top, an OF
 *  profile in a new tab. */
export function linkUser(links: Iterable<Element>, href: string | null) {
  if (!href) return;
  const away = href.startsWith("https://");
  for (const a of links) {
    a.setAttribute("href", href);
    a.setAttribute("target", away ? "_blank" : "_top");
    if (away) a.setAttribute("rel", "noopener noreferrer");
    else a.removeAttribute("rel");
  }
}
export const sameId = (a: unknown, b: string | null | undefined) => b != null && String(a) === b;
/** OF message text (HTML) as plain text, parsed inertly. */
export const plain = (html: string | null | undefined) => (html ? (new DOMParser().parseFromString(html, "text/html").body.textContent ?? "").trim() : "");
/**
 * OF's text markup (a bio's `about`, a message's text; parsed inertly) as its plain lines: one per paragraph, a <br>
 * breaking a line; nl2br's "<br />\n" is one break, not two.
 */
export function htmlLines(html: string | null | undefined): string[] {
  if (!html) return [];
  const body = new DOMParser().parseFromString(html.replace(/(<br\s*\/?>)\r?\n/gi, "$1"), "text/html").body;
  for (const br of body.querySelectorAll("br")) br.replaceWith("\n");
  const ps = [...body.querySelectorAll("p")];
  return (ps.length > 1 ? ps.map((p) => p.textContent ?? "").join("\n") : (body.textContent ?? "")).split("\n");
}
/** A source's body once read as an object, else null (loading, or it failed). */
export const objectOf = <T extends object>(v: unknown): T | null => (v && typeof v === "object" ? (v as T) : null);
/** Put `el` in OF's empty v-if slot (an empty comment) after, before or last in `ref`, else there itself. */
export function fillSlot(ref: Element, where: "after" | "before" | "append", el: Node) {
  const slot = where === "after" ? ref.nextSibling : where === "before" ? ref.previousSibling : ref.lastChild;
  if (slot?.nodeType === 8) slot.replaceWith(el);
  else ref[where](el);
}

export const valid = (iso?: string) => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? d : null;
};
/** "5:06 am", "Oct 11", "Oct 12, 5:06 am": OF's formats. */
export const clock = clockTime;
export const dayOf = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
export const stamp = (d: Date) => `${dayOf(d)}, ${clock(d)}`;

/** Show `img(avatar)` in an avatar link: its <img>, or the letter placeholder swapped for OF's image markup. */
export function setAvatar(el: Element | null, u: OFUserMini, img: (u: string) => string) {
  if (!el) return;
  el.classList.remove("has-story", "has-new-story"); // the example's story ring
  el.querySelector(".g-avatar__icon")?.remove(); // and its online dot
  const ph = el.querySelector<HTMLElement>(".g-avatar__placeholder");
  // OF's text avatar (the same avatar component as a list's member stack): its initials; a login-only name (none) keeps
  // its first letter, OF's profile icon not being in every page's sprite.
  if (ph) ph.textContent = ` ${initials(u) || ([...nameOf(u)][0] ?? "")} `;
  if (!u.avatar) return;
  const pic = el.querySelector("img");
  if (pic) pic.setAttribute("src", img(u.avatar));
  else if (ph) {
    // The placeholder's own ::after would cover a background image.
    const doc = ph.ownerDocument;
    const scope = [...ph.attributes].filter((a) => a.name.startsWith("data-v-"));
    const wrap = doc.createElement("div");
    for (const a of scope) wrap.setAttribute(a.name, a.value);
    wrap.className = "g-avatar__img-wrapper";
    const pic = doc.createElement("img");
    if (scope[0]) pic.setAttribute(scope[0].name, scope[0].value);
    pic.setAttribute("src", img(u.avatar));
    pic.setAttribute("alt", "");
    pic.setAttribute("loading", "lazy");
    wrap.appendChild(pic);
    ph.replaceWith(wrap);
  }
}

/**
 * Someone else's avatar in a cloned row's avatar link `el`: `u`'s picture, else no picture at all (setAvatar would keep
 * the template's), and its letter placeholder marked .of-fan: not the Creator's avatar, so useOfIdentity leaves it.
 */
export function otherAvatar(el: Element | null, u: OFUserMini | undefined, img: (u: string) => string) {
  setAvatar(el, u ?? { id: "" }, img);
  if (!u?.avatar) {
    const pic = el?.querySelector("img");
    (pic?.closest(".g-avatar__img-wrapper") ?? pic)?.remove();
  }
  el?.querySelector(".g-avatar__placeholder")?.classList.add("of-fan");
}

export const ROW_MARKS = ["m-current", "router-link-active"];

/** Point the OF icon in `el` (its svg and <use>s) at `icon`. */
export function setIcon(el: Element, icon: string) {
  el.querySelector("svg")?.setAttribute("data-icon-name", icon);
  for (const use of el.querySelectorAll("use")) {
    use.setAttribute("href", `#${icon}`);
    use.setAttribute("xlink:href", `#${icon}`);
  }
}

/** Mark `a` (a list row's link) the open row, as OF does. */
export function markOpen(a: Element | null) {
  if (!a) return;
  a.classList.add(...ROW_MARKS);
  a.setAttribute("aria-current", "page");
}

/** "0:56", "1:02:03": OF's video duration label. */
export const duration = (sec: number) => {
  const s = Math.round(sec);
  const mmss = `${Math.floor((s % 3600) / 60)}:${String(s % 60).padStart(2, "0")}`;
  return s >= 3600 ? `${Math.floor(s / 3600)}:${mmss.padStart(5, "0")}` : mmss;
};

/** Flip OF's `selected` mark on a vault tile and its checkbox (set it to `force` when given); returns the new state. */
export function toggleTile(tile: Element, force?: boolean): boolean {
  const on = tile.classList.toggle("selected", force);
  tile.querySelector(".checkbox-item")?.classList.toggle("selected", on);
  return on;
}

/** The page's media grid (vault, My profile's Media tab): its example rows and tiles. */
export function photoGrid(doc: Document) {
  const grid = doc.querySelector(".b-photos .vue-recycle-scroller__item-wrapper");
  return {
    views: grid ? [...grid.querySelectorAll<HTMLElement>(":scope > .vue-recycle-scroller__item-view")] : [],
    tiles: grid ? [...grid.querySelectorAll<HTMLElement>(".b-photos__item")] : [],
  };
}

/** `tiles` three to a row, in copies of the grid's first row, in place of its example `views`. */
export function fillGrid(doc: Document, views: HTMLElement[], tiles: HTMLElement[]) {
  const rowTpl = make(views[0]);
  rowTpl.style.removeProperty("display"); // the generator's hidden template (the Vault page's)
  rowTpl.querySelector(".dynamic-scroller-item")?.replaceChildren();
  const rows: HTMLElement[] = [];
  tiles.forEach((t, i) => {
    if (i % 3 === 0) rows.push(rowTpl.cloneNode(true) as HTMLElement);
    const holder = rows[rows.length - 1];
    (holder.querySelector(".dynamic-scroller-item") ?? holder).appendChild(t);
  });
  fill(doc, views, rows);
}

/** An infinite list's next page (Statements' Earnings, a list's Posts tab), OF's infinite loading row: being read, its error, or `next` asks for it (null: no more). */
export interface MorePages {
  loading: boolean;
  error: string | null;
  next: (() => void) | null;
}

/** OF's infinite loading row (vue-infinite-loading's prompts: spinner, no more, no results, error): see applyTransactions. */
export function applyMore(doc: Document, body: Element, more: MorePages) {
  const box = body.querySelector<HTMLElement>(".infinite-loading-container");
  if (!box) return;
  const [spinner, , , failed] = box.querySelectorAll<HTMLElement>(":scope > .infinite-status-prompt");
  const show = (el: HTMLElement | undefined) => {
    if (!el) return;
    const was = el.getAttribute("style");
    track(doc, () => (was === null ? el.removeAttribute("style") : el.setAttribute("style", was)));
    el.style.removeProperty("display");
  };
  if (more.loading) return show(spinner);
  if (more.error !== null) {
    show(failed);
    const retry = failed?.querySelector("button");
    const next = more.next;
    if (retry && next) {
      retry.addEventListener("click", next);
      track(doc, () => retry.removeEventListener("click", next));
    }
    return;
  }
  const next = more.next;
  const IO = doc.defaultView?.IntersectionObserver;
  if (!next || !IO) return;
  // The frame's own document as root: the top page's viewport clips the frame, so its margin would stop at the frame's end
  // and a row just under it (Home's, scrolled to the bottom) would never ask.
  const io = new IO((entries) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    io.disconnect();
    next();
  }, { root: doc, rootMargin: "0px 0px 300px 0px" });
  io.observe(box);
  track(doc, () => io.disconnect());
}
