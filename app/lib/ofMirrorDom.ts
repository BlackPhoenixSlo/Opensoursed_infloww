"use client";


import type { OFUserMini } from "@/lib/relay";
import { clockTime } from "@/lib/format";
import { undoList } from "@/lib/ofMirrorUndo";
import { initials } from "@/lib/ofMirrorAvatar";
import { setOfHtml } from "@/lib/ofMirrorFormat";
import { isOfHtml } from "@/lib/ofRichText";

export type Part = "chats" | "chatList" | "thread" | "gallery" | "vaultLists" | "vaultMedia" | "userLists" | "listRow" | "listUsers" | "listPosts" | "subscribers" | "labels" | "posts" | "profileMedia" | "bookmarks" | "queue" | "notifications" | "transactions" | "payouts" | "referrals"
  | "home" | "stories" | "notificationCounts" | "pastStreams" | "promotions" | "events" | "profile";

export const { track, own, setAttr, setClass, setText, restore } = undoList({ attrMode: "single", classUndo: "snapshot", skipEqualText: false });
export function dropClass(doc: Document, el: Element, ...cls: string[]) {
  setAttr(doc, el, "class", [...el.classList].filter((c) => !cls.includes(c)).join(" "));
}

export function make(tpl: Element): HTMLElement {
  const c = tpl.cloneNode(true) as HTMLElement;
  for (const el of [c, ...c.querySelectorAll<HTMLElement>("*")]) {
    for (const a of [...el.attributes]) if (a.name.startsWith("data-oi-")) el.removeAttribute(a.name);
  }
  c.dataset.oiData = "";
  return c;
}

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
export function userHref(u: { id?: unknown; username?: string | null } | null | undefined, me?: string | null): string | null {
  const id = u?.id == null || u.id === "" ? null : String(u.id);
  if (id == null && !u?.username) return null;
  if (me != null && id === me) return "/of-manager/profile";
  return `https://onlyfans.com/${encodeURIComponent(u?.username || `u${id}`)}`;
}
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
export const plain = (html: string | null | undefined) =>
  html ? (new DOMParser().parseFromString(html.replace(/<br\s*\/?>|<\/p\s*>/gi, "$& "), "text/html").body.textContent ?? "").trim() : "";
export function setOfText(holder: Element, text: string, proto?: Element | null): void {
  setOfHtml(holder, isOfHtml(text) ? text : `<p>${text}</p>`);
  if (proto) for (const p of holder.querySelectorAll(":scope > p")) for (const a of proto.attributes) p.setAttribute(a.name, a.value);
}
export function htmlLines(html: string | null | undefined): string[] {
  if (!html) return [];
  const body = new DOMParser().parseFromString(html.replace(/(<br\s*\/?>)\r?\n/gi, "$1"), "text/html").body;
  for (const br of body.querySelectorAll("br")) br.replaceWith("\n");
  const ps = [...body.querySelectorAll("p")];
  return (ps.length > 1 ? ps.map((p) => p.textContent ?? "").join("\n") : (body.textContent ?? "")).split("\n");
}
export const objectOf = <T extends object>(v: unknown): T | null => (v && typeof v === "object" ? (v as T) : null);
export function fillSlot(ref: Element, where: "after" | "before" | "append", el: Node) {
  const slot = where === "after" ? ref.nextSibling : where === "before" ? ref.previousSibling : ref.lastChild;
  if (slot?.nodeType === 8) slot.replaceWith(el);
  else ref[where](el);
}

export function floatLabel(input: HTMLInputElement | HTMLTextAreaElement, filled: boolean) {
  const field = input.closest(".v-input");
  if (!field) return;
  for (const c of ["v-input--is-label-active", "v-input--is-dirty"]) field.classList.toggle(c, filled);
  const label = field.querySelector<HTMLElement>(".v-label");
  label?.classList.toggle("v-label--active", filled);
  const legend = field.querySelector<HTMLElement>("legend");
  if (legend && label) legend.style.width = filled ? `${label.scrollWidth * 0.75 + 6}px` : "0px";
}

export const valid = (iso?: string) => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? d : null;
};
export const clock = clockTime;
export const dayOf = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
export const stamp = (d: Date) => `${dayOf(d)}, ${clock(d)}`;

export function setAvatar(el: Element | null, u: OFUserMini, img: (u: string) => string) {
  if (!el) return;
  el.classList.remove("has-story", "has-new-story");
  // A login-only name keeps its first letter: OF's profile icon is not in every page's sprite.
  el.querySelector(".g-avatar__icon")?.remove();
  const ph = el.querySelector<HTMLElement>(".g-avatar__placeholder");
  if (ph) ph.textContent = ` ${initials(u) || ([...nameOf(u)][0] ?? "")} `;
  if (!u.avatar) return;
  const pic = el.querySelector("img");
  if (pic) pic.setAttribute("src", img(u.avatar));
  else if (ph) {
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

export function otherAvatar(el: Element | null, u: OFUserMini | undefined, img: (u: string) => string) {
  setAvatar(el, u ?? { id: "" }, img);
  if (!u?.avatar) {
    const pic = el?.querySelector("img");
    (pic?.closest(".g-avatar__img-wrapper") ?? pic)?.remove();
  }
  el?.querySelector(".g-avatar__placeholder")?.classList.add("of-fan");
}

export const ROW_MARKS = ["m-current", "router-link-active"];

export function setIcon(el: Element, icon: string) {
  el.querySelector("svg")?.setAttribute("data-icon-name", icon);
  for (const use of el.querySelectorAll("use")) {
    use.setAttribute("href", `#${icon}`);
    use.setAttribute("xlink:href", `#${icon}`);
  }
}

export function markOpen(a: Element | null) {
  if (!a) return;
  a.classList.add(...ROW_MARKS);
  a.setAttribute("aria-current", "page");
}

export const duration = (sec: number) => {
  const s = Math.round(sec);
  const mmss = `${Math.floor((s % 3600) / 60)}:${String(s % 60).padStart(2, "0")}`;
  return s >= 3600 ? `${Math.floor(s / 3600)}:${mmss.padStart(5, "0")}` : mmss;
};

export function toggleTile(tile: Element, force?: boolean): boolean {
  const on = tile.classList.toggle("selected", force);
  tile.querySelector(".checkbox-item")?.classList.toggle("selected", on);
  return on;
}

export function photoGrid(doc: Document) {
  const grid = doc.querySelector(".b-photos .vue-recycle-scroller__item-wrapper");
  return {
    views: grid ? [...grid.querySelectorAll<HTMLElement>(":scope > .vue-recycle-scroller__item-view")] : [],
    tiles: grid ? [...grid.querySelectorAll<HTMLElement>(".b-photos__item")] : [],
  };
}

export function fillGrid(doc: Document, views: HTMLElement[], tiles: HTMLElement[]) {
  const rowTpl = make(views[0]);
  rowTpl.style.removeProperty("display");
  rowTpl.querySelector(".dynamic-scroller-item")?.replaceChildren();
  const rows: HTMLElement[] = [];
  tiles.forEach((t, i) => {
    if (i % 3 === 0) rows.push(rowTpl.cloneNode(true) as HTMLElement);
    const holder = rows[rows.length - 1];
    (holder.querySelector(".dynamic-scroller-item") ?? holder).appendChild(t);
  });
  fill(doc, views, rows);
}

export interface MorePages {
  loading: boolean;
  error: string | null;
  next: (() => void) | null;
}

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
  // The frame's own document is the root: the top page's viewport clips the frame, so a row just under it would never ask.
  const IO = doc.defaultView?.IntersectionObserver;
  if (!next || !IO) return;
  const io = new IO((entries) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    io.disconnect();
    next();
  }, { root: doc, rootMargin: "0px 0px 300px 0px" });
  io.observe(box);
  track(doc, () => io.disconnect());
}
