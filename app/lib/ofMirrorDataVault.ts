"use client";


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

function setCounts(thumbs: Element, l: Partial<VaultList>) {
  const itemTpl = thumbs.querySelector(".b-content-inside-thumbs__item");
  if (!itemTpl) return;
  const items = VAULT_COUNTS.filter(([k]) => Number(l[k] ?? 0) > 0).map(([k, icon]) => {
    const it = itemTpl.cloneNode(true) as HTMLElement;
    it.style.removeProperty("display");
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

export function applyVaultAll(doc: Document, all: Partial<VaultList>, base: string, img: (u: string) => string, search?: string | null) {
  const row = [...doc.querySelectorAll<HTMLElement>(".b-rows-lists__item")].find((r) => r.querySelector(`a[href='${base}']`));
  const thumbs = row?.querySelector(".b-content-inside-thumbs");
  if (!row || !thumbs) return;
  // As OF's showAllMedia: during a folder search the row shows only while its name starts with the query (lowercased, accents stripped).
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
    if (!setCovers(set, all.medias, img)) set.style.display = "none";
  }
  const was = [...thumbs.childNodes];
  track(doc, () => thumbs.replaceChildren(...was));
  setCounts(thumbs, all);
}

export function applyListSort(doc: Document, sort: string, base: string) {
  const path = base.split("?")[0];
  const all = doc.querySelector(`.b-rows-lists__item a[href='${path}'], .b-rows-lists__item a[href^='${path}?']`);
  const title = all?.closest(".l-sidebar-column")?.querySelector(".b-content-filter__title");
  if (title) setText(doc, title, LIST_SORTS[sort] ?? sort);
}

export function applyVaultLists(doc: Document, lists: VaultList[], open: string | null, base: string, img: (u: string) => string) {
  const rows = [...doc.querySelectorAll<HTMLElement>(".b-rows-lists__item")].filter((r) => r.querySelector("a[href^='/of-manager/vault/list']"));
  if (!rows.length) return;
  const tpl = rows.find((r) => r.querySelector(".b-content-inside-thumbs__icon")) ?? rows[0];
  const isOpen = lists.some((l) => sameId(l.id, open));
  const clones = lists.map((l) => {
    const el = make(tpl);
    el.style.removeProperty("display");
    const a = el.querySelector("a")!;
    a.setAttribute("href", `${base}${base.includes("?") ? "&" : "?"}list=${encodeURIComponent(String(l.id))}`);
    a.classList.remove(...ROW_MARKS, "m-current");
    a.removeAttribute("aria-current");
    if (sameId(l.id, open)) markOpen(a);
    el.querySelector(".b-rows-lists__item__name")!.textContent = l.name;
    const set = el.querySelector<HTMLElement>(".b-media-set");
    if (set && !setCovers(set, l.medias, img)) set.remove();
    const thumbs = el.querySelector(".b-content-inside-thumbs");
    if (thumbs) setCounts(thumbs, l);
    return el;
  });
  fill(doc, rows, clones);
  if (isOpen) {
    for (const a of doc.querySelectorAll(".b-rows-lists__item:not([data-oi-data]) a.b-rows-lists__item__text")) {
      dropClass(doc, a, ...ROW_MARKS);
      setAttr(doc, a, "aria-current", null);
    }
  }
}

const tileThumb = (m: VaultMedia, img: (u: string) => string) => {
  const u = m.files?.thumb?.url || m.files?.squarePreview?.url || m.files?.preview?.url;
  return m._thumb || (u ? img(u) : "");
};

const BADGE: Record<string, string> = { video: "icon-video", gif: "icon-gif", audio: "icon-voice" };

export function applyVaultMedia(doc: Document, media: NonNullable<MirrorData["vaultMedia"]>, img: (u: string) => string, picked?: (number | string)[]) {
  const { views, tiles } = photoGrid(doc);
  const photoTpl = tiles.find((t) => !t.querySelector(".m-video-duration, .b-photos__item__play-btn"));
  if (!views.length || !photoTpl) return;
  const videoTpl = tiles.find((t) => t.querySelector(".m-video-duration"));
  const els = media.map((m) => {
    const badge = videoTpl && Object.hasOwn(BADGE, m.type) ? BADGE[m.type] : null;
    const el = make(badge ? videoTpl! : photoTpl);
    delete el.dataset.oiData;
    el.dataset.oiMedia = String(m.id);
    if (picked) {
      el.setAttribute("data-oi-wired", "");
      if (picked.some((p) => sameId(m.id, String(p)))) toggleTile(el, true);
    }
    el.querySelector(".b-media-purchased-icon")?.remove();
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
    const full = (m.type === "video" || m.type === "gif" ? m.videoSources?.["720"] : null) || m.files?.full?.url;
    if (full) el.dataset.oiFull = img(full);
    el.dataset.oiType = m.type;
    return el;
  });
  fillGrid(doc, views, els);
  if (els.length) for (const e of doc.querySelectorAll(".b-photos [data-oi-empty]")) setAttr(doc, e, "style", "display:none");
}

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
