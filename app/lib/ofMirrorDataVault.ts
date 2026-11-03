"use client";

/** The vault's rows, cut from ofMirrorData (applyData draws them): the folder column (All media, the folders, their sort) and the media grid. */

import type { VaultList, VaultMedia } from "@/lib/relay";
import { LIST_SORTS } from "@/lib/ofMirrorVault";
import { dayOf, dropClass, duration, fill, fillGrid, make, markOpen, photoGrid, ROW_MARKS, sameId, setAttr, setIcon, setText, stamp, toggleTile, track, valid } from "@/lib/ofMirrorDom";
import type { MirrorData } from "@/lib/ofMirrorDataOf";

const VAULT_COUNTS: [keyof VaultList, string][] = [
  ["photosCount", "icon-image"],
  ["videosCount", "icon-video"],
  ["gifsCount", "icon-gif"],
  ["audiosCount", "icon-voice"],
];

/** A folder row's counts line: one OF count per kind it has (photos, videos, GIFs, audio), else "empty". */
function setCounts(thumbs: Element, l: Partial<VaultList>) {
  const itemTpl = thumbs.querySelector(".b-content-inside-thumbs__item");
  if (!itemTpl) return;
  const items = VAULT_COUNTS.filter(([k]) => Number(l[k] ?? 0) > 0).map(([k, icon]) => {
    const it = itemTpl.cloneNode(true) as HTMLElement;
    it.style.removeProperty("display"); // the generator's hidden template
    setIcon(it, icon);
    while (it.lastChild?.nodeType === 3) it.lastChild.remove();
    it.append(` ${l[k]} `);
    return it;
  });
  if (!items.length) {
    const it = itemTpl.cloneNode(false) as HTMLElement;
    it.style.removeProperty("display");
    it.textContent = "empty";
    items.push(it);
  }
  thumbs.replaceChildren(...items);
}

/**
 * A folder row's covers (`set`, OF's .b-media-set): one copy of its hidden, pictureless cover per picture in `medias`
 * (OF's newest three, through `img`), the set shown; none: the set stays hidden. Returns how many.
 */
function setCovers(set: HTMLElement, medias: VaultList["medias"], img: (u: string) => string): number {
  const tpl = set.querySelector(".b-media-set__item");
  if (!tpl) return 0;
  const covers = (medias ?? []).filter((m) => m?.url).slice(0, 3).map((m) => {
    const it = tpl.cloneNode(true) as HTMLElement;
    it.querySelector("img")?.setAttribute("src", img(m.url!));
    return it;
  });
  if (!covers.length) return 0;
  set.replaceChildren(...covers);
  set.style.removeProperty("display");
  return covers.length;
}

/** The vault's "All media" row (the one linking to `base`, the page's own): the real counts and covers. */
export function applyVaultAll(doc: Document, all: Partial<VaultList>, base: string, img: (u: string) => string, search?: string | null) {
  const row = [...doc.querySelectorAll<HTMLElement>(".b-rows-lists__item")].find((r) => r.querySelector(`a[href='${base}']`));
  const thumbs = row?.querySelector(".b-content-inside-thumbs");
  if (!row || !thumbs) return;
  // OF's showAllMedia: during a folder search the row shows only while its name starts with the query (both lowercased
  // and stripped of accents).
  const fold = (t: string) => t.trim().toLowerCase().normalize("NFD").replace(/\p{M}/gu, "");
  if (search && !fold(row.querySelector(".b-rows-lists__item__name")?.textContent ?? "All media").startsWith(fold(search))) {
    const display = row.style.display;
    track(doc, () => void (row.style.display = display));
    row.style.display = "none";
  }
  const set = row.querySelector<HTMLElement>(".b-media-set");
  if (set) {
    const [kids, style] = [[...set.childNodes], set.getAttribute("style")];
    track(doc, () => {
      set.replaceChildren(...kids);
      if (style === null) set.removeAttribute("style");
      else set.setAttribute("style", style);
    });
    // No covers: no picture shows, not even a captured example's (a composer's vault dialog keeps its row's).
    if (!setCovers(set, all.medias, img)) set.style.display = "none";
  }
  const was = [...thumbs.childNodes];
  track(doc, () => thumbs.replaceChildren(...was));
  setCounts(thumbs, all);
}

/**
 * The folder column's title (the Vault page's, a composer's vault dialog's: the column holding the "All media" row that
 * links to `base`) is the folders' sort, as OF's (the `sort` GET /vault/lists answers), not the capture's "custom".
 */
export function applyListSort(doc: Document, sort: string, base: string) {
  const path = base.split("?")[0]; // a chat's dialog: its All media row's ?chat= or not
  const all = doc.querySelector(`.b-rows-lists__item a[href='${path}'], .b-rows-lists__item a[href^='${path}?']`);
  const title = all?.closest(".l-sidebar-column")?.querySelector(".b-content-filter__title");
  if (title) setText(doc, title, LIST_SORTS[sort] ?? sort);
}

/** The vault's folder rows, each linking to `base` with its ?list= (the Vault page, or a composer's vault dialog). */
export function applyVaultLists(doc: Document, lists: VaultList[], open: string | null, base: string, img: (u: string) => string) {
  const rows = [...doc.querySelectorAll<HTMLElement>(".b-rows-lists__item")].filter((r) => r.querySelector("a[href^='/of-manager/vault/list']"));
  if (!rows.length) return;
  const tpl = rows.find((r) => r.querySelector(".b-content-inside-thumbs__icon")) ?? rows[0];
  const isOpen = lists.some((l) => sameId(l.id, open));
  const clones = lists.map((l) => {
    const el = make(tpl);
    el.style.removeProperty("display"); // the generator's hidden template
    const a = el.querySelector("a")!;
    a.setAttribute("href", `${base}${base.includes("?") ? "&" : "?"}list=${encodeURIComponent(String(l.id))}`);
    a.classList.remove(...ROW_MARKS, "m-current");
    a.removeAttribute("aria-current");
    if (sameId(l.id, open)) markOpen(a);
    el.querySelector(".b-rows-lists__item__name")!.textContent = l.name;
    // OF draws no set for a folder without media.
    const set = el.querySelector<HTMLElement>(".b-media-set");
    if (set && !setCovers(set, l.medias, img)) set.remove();
    const thumbs = el.querySelector(".b-content-inside-thumbs");
    if (thumbs) setCounts(thumbs, l);
    return el;
  });
  fill(doc, rows, clones);
  if (isOpen) {
    // "All media" (and any other row still shown) is no longer the open one.
    for (const a of doc.querySelectorAll(".b-rows-lists__item:not([data-oi-data]) a.b-rows-lists__item__text")) {
      dropClass(doc, a, ...ROW_MARKS);
      setAttr(doc, a, "aria-current", null);
    }
  }
}

/** A vault tile's picture: the relay's stored square, else OF's thumb (through `img`). */
const tileThumb = (m: VaultMedia, img: (u: string) => string) => {
  const u = m.files?.thumb?.url || m.files?.squarePreview?.url || m.files?.preview?.url;
  return m._thumb || (u ? img(u) : "");
};

/** The kinds whose tile carries OF's duration badge, and the badge's icon (OF's sprite; a video's as captured). */
const BADGE: Record<string, string> = { video: "icon-video", gif: "icon-gif", audio: "icon-voice" };

/**
 * The vault's right-hand grid (also New post's vault dialog): one OF tile per media (a video's with its
 * duration and play button; a GIF's and an audio's with the duration badge under their own icon; a media with no picture,
 * as an audio's, keeps the grey placeholder), three to a row, each stamped `data-oi-media="<vault id>"` and `data-oi-text` (what the
 * dialog's search matches: its date label, plus the AI description and tags when the Relay sends them), `data-oi-type` and
 * `data-oi-full` (the file the Vault page's viewer shows). With `picked` (a
 * picker: New post's dialog, whose clicks ofMirrorPost handles) every tile is wired and the picked ones selected.
 */
export function applyVaultMedia(doc: Document, media: NonNullable<MirrorData["vaultMedia"]>, img: (u: string) => string, picked?: (number | string)[]) {
  const { views, tiles } = photoGrid(doc);
  const photoTpl = tiles.find((t) => !t.querySelector(".m-video-duration, .b-photos__item__play-btn"));
  if (!views.length || !photoTpl) return;
  const videoTpl = tiles.find((t) => t.querySelector(".m-video-duration"));
  const els = media.map((m) => {
    const badge = videoTpl && Object.hasOwn(BADGE, m.type) ? BADGE[m.type] : null;
    const el = make(badge ? videoTpl! : photoTpl);
    delete el.dataset.oiData;
    el.dataset.oiMedia = String(m.id); // the vault id a pick sends
    if (picked) {
      el.setAttribute("data-oi-wired", "");
      if (picked.some((p) => sameId(m.id, String(p)))) toggleTile(el, true);
    }
    el.querySelector(".b-media-purchased-icon")?.remove(); // the example's purchase state
    const at = valid(m.createdAt);
    el.dataset.oiText = [at && dayOf(at), m._ai?.description, ...(m._ai?.tags ?? [])].filter(Boolean).join(" ");
    const stampEl = el.querySelector(".b-element-label.m-timestamp:not(.m-video-duration)");
    if (stampEl && at) {
      stampEl.textContent = ` ${dayOf(at)} `;
      stampEl.setAttribute("title", stamp(at));
    } else stampEl?.remove();
    const label = el.querySelector(".m-video-duration");
    if (label && badge) setIcon(label, badge);
    const dur = label?.querySelector("span");
    if (dur) {
      if (m.duration) dur.textContent = duration(m.duration);
      else dur.remove();
    }
    if (m.type !== "video") el.querySelector(".b-photos__item__play-btn")?.remove();
    const thumb = tileThumb(m, img);
    if (thumb) el.querySelector(".b-photos__item__img")?.setAttribute("src", thumb);
    // What the Vault page's viewer shows (through `img`): a video's or GIF's 720p (else its source file), else the full file.
    const full = (m.type === "video" || m.type === "gif" ? m.videoSources?.["720"] : null) || m.files?.full?.url;
    if (full) el.dataset.oiFull = img(full);
    el.dataset.oiType = m.type;
    return el;
  });
  fillGrid(doc, views, els);
  // The Vault page's "Nothing found" (the generator's) only for no media.
  if (els.length) for (const e of doc.querySelectorAll(".b-photos [data-oi-empty]")) setAttr(doc, e, "style", "display:none");
}

/**
 * The Vault page's grid before its media are here: OF's "Nothing found" reads "Loading media…" while the Relay answers
 * (`error` null), or the red "Could not load media: <the Relay's text>" after it failed (as the chat list).
 */
export function applyVaultStatus(doc: Document, error: string | null) {
  const text = doc.querySelector<HTMLElement>(".b-photos [data-oi-empty] .empty-message > span");
  if (!text) return;
  const [was, style] = [text.textContent, text.getAttribute("style")];
  track(doc, () => {
    text.textContent = was;
    if (style === null) text.removeAttribute("style");
    else text.setAttribute("style", style);
  });
  text.textContent = error === null ? "Loading media…" : `Could not load media: ${error}`;
  if (error !== null) text.style.color = "#ff4545";
}
