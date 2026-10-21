"use client";

/**
 * OF's avatar as the mirror draws it (the Statistics fan cells, a list row's member stack, Stream's blocked users, the
 * tag dialog): picture, else OF's text avatar (initials), else its profile icon; and the two element builders it needs.
 * A leaf: imports nothing of the mirror, so ofMirrorData and the Statistics modules can both use it.
 */

/** An element of `doc` with OF's classes and text. */
export const elOf = (doc: Document) => (tag: string, cls = "", text?: string) => {
  const e = doc.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
/** OF's icon (`<svg class="g-icon"><use href="#icon-…">`). */
export function iconOf(doc: Document, name: string, cls = "g-icon") {
  const svg = doc.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("data-icon-name", `icon-${name}`);
  svg.setAttribute("class", cls);
  const use = doc.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#icon-${name}`);
  use.setAttribute("xlink:href", `#icon-${name}`);
  svg.append(use);
  return svg;
}
/** A user OF draws an avatar for: a fan it lists (`/subscriptions/subscribers/*`, `/users/me/referrals`, the top fan), a list's member, a post's author, a blocked user. */
export interface AvatarUser {
  id?: number | string;
  name?: string | null;
  username?: string | null;
  avatar?: string | null;
  avatarThumbs?: { c50?: string | null; c144?: string | null } | null;
  /** The Creator's rename of the user: OF's initials are of it over `name`. */
  displayName?: string | null;
  isActive?: boolean;
  isDeleted?: boolean;
}
/** The Statistics pages' name for it (their users are fans). */
export type Fan = AvatarUser;
/** OF's text avatar (its avatar component's initials): one word's first two (its first emoji out), else two words' first letters. */
export function textAvatar(name: string): string {
  const emoji = /(\u00a9|\u00ae|[\u2000-\u3300]|\ud83c[\ud000-\udfff]|\ud83d[\ud000-\udfff]|\ud83e[\ud000-\udfff])/;
  const words = name.split(/\s+/);
  if (words.length < 2) return name.replace(emoji, "").substring(0, 2).split("").map((c, i) => (i ? c : c.toUpperCase())).join("");
  const out: string[] = [];
  for (const w of words.slice(0, 2)) {
    const c = [...w.trim()][0] ?? "";
    if (out.length < 1 || (!emoji.test(out[0]) && !emoji.test(c))) out.push(c);
  }
  return out.join("").toUpperCase();
}
/** OF's initials avatar ("Cl" for Cliff, "M2" for "Marcus, 29"), of the display name over the name; a user named only by
 *  its login (`u<id>`, no display name): none, OF's profile icon instead. */
export const initials = (u: AvatarUser) => {
  const name = (u.displayName || u.name || "").trim();
  if (!name || (!u.displayName && u.name === `u${u.id}`)) return "";
  return textAvatar(name);
};
/** OF's avatar (`g-avatar`): the picture through the Relay's image proxy, else initials, else the profile icon. */
export function avatarOf(doc: Document, u: AvatarUser, size: 36 | 50, img: ((u: string) => string) | undefined, cls = "m-absolute") {
  const el = elOf(doc);
  const box = el("span", `g-avatar m-reset-wcag-link-focus ${cls} m-w${size}`);
  box.setAttribute("data-v-710dd05d", "");
  const pic = u.avatarThumbs?.c144 ?? u.avatarThumbs?.c50 ?? u.avatar;
  if (pic && img) {
    const w = el("div", "g-avatar__img-wrapper");
    w.setAttribute("data-v-710dd05d", "");
    const i = el("img") as HTMLImageElement;
    i.src = img(pic);
    i.alt = "";
    w.append(i);
    box.append(w);
  } else {
    const ini = initials(u);
    const ph = el("div", `g-avatar__placeholder${ini ? " m-text-avatar" : ""}`, ini ? ` ${ini} ` : undefined);
    ph.setAttribute("data-v-8dd7beb8", "");
    ph.setAttribute("data-v-710dd05d", "");
    if (!ini) ph.append(iconOf(doc, "profile", "b-default-avatar g-icon"));
    box.append(ph);
  }
  return box;
}
