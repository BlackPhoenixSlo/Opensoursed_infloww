"use client";


import { createContext, useContext, useEffect, type RefObject } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { useUser } from "@/contexts/UserContext";
import { useAccounts, usePlatformAccounts } from "@/hooks/useAccounts";
import { relay, type AccountMeta } from "@/lib/relay";
import type { Platform } from "@/lib/platform";
import { liveSession } from "@/lib/sessionConnectivity";
import { proxyImage } from "@/lib/mediaUrl";
import { stillUrl } from "@/lib/ofMedia";
import type { PostLabel } from "@/lib/ofMirrorDataLists";
import { fill, make, setAttr, setText, track, valid } from "@/lib/ofMirrorDom";
import type { MirrorPost } from "@/lib/ofMirrorFeedsShared";
import { fitBio, foldBio, formatCount, ofMeQuery } from "@/lib/ofMirrorIdentity";
import { showMenu } from "@/lib/ofMirrorMenu";
import { message, note, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { toast } from "@/lib/ofMirrorPost";

const PROFILE_SRC = /^\/of-mirror\/pages\/profile\//;
const STAND_IN_SRC = /^\/of-mirror\/pages\/(?:profile\/|release-forms\/|messages\/|queue\/|new-post\/|statistics\/|vault\/|settings\/|home\/state-avatar-menu\.html|statements\/(?:index|earnings)\.html$)/;

type StandInCandidate = Pick<AccountMeta, "id" | "has_session" | "session_dead_at">;

export function standInPick(accounts: readonly StandInCandidate[]): string | null {
  return (accounts.find(liveSession) ?? accounts[0])?.id ?? null;
}

export const AutoPickContext = createContext<{ platform: Platform; accountId: string | null } | null>(null);

export function standInModel(
  src: string, accountId: string | null, accounts: readonly StandInCandidate[], auto: string | null = null,
): string | null {
  return !accountId && STAND_IN_SRC.test(src) ? auto ?? standInPick(accounts) : null;
}

const lastStandIn = new Map<string, string>();

export function useStandIn(src: string): string | null {
  const { accountId: scoped } = useScope();
  const route = useContext(AutoPickContext);
  const auto = route?.accountId ?? null;
  const accountId = auto !== null && scoped === auto ? null : scoped;
  const principal = useUser().user?.user_id ?? "";
  const accounts = useAccounts().data?.accounts;
  const routeAccounts = usePlatformAccounts(route?.platform);
  const cacheKey = JSON.stringify([principal, route?.platform ?? null]);
  const cached = accounts?.length ? null : lastStandIn.get(cacheKey) ?? null;
  const standIn = standInModel(src, accountId, routeAccounts, auto ?? cached);
  useEffect(() => {
    if (standIn) lastStandIn.set(cacheKey, standIn);
  }, [cacheKey, standIn]);
  return standIn;
}

export const PROFILE_CHANGE = "oi-profile-change";

export interface ProfileUser {
  postsCount?: number | null;
  mediasCount?: number | null;
  photosCount?: number | null;
  videosCount?: number | null;
  favoritedCount?: number | null;
  subscribersCount?: number | null;
  archivedPostsCount?: number | null;
  privateArchivedPostsCount?: number | null;
}

export interface Highlight {
  id: number | string;
  title?: string | null;
  cover?: string | null;
  storiesCount?: number | null;
}

export interface MirrorProfile {
  user: ProfileUser;
  labels?: PostLabel[];
  highlights?: Highlight[];
}

export type MediaPost = MirrorPost & { _kind?: "photo" | "video" };

const num = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const words = (el: Element) => (el.textContent ?? "").replace(/\s+/g, " ").trim();
const SYSTEM_LABELS = new Set(["archived", "private_archived"]);

export function applyProfile(doc: Document, p: MirrorProfile, img: (u: string) => string) {
  const u = p.user;
  const sections: [string, unknown][] = [
    ["Photos", u.photosCount],
    ["Videos", u.videosCount],
    ["Likes", u.favoritedCount],
    ["Fans", u.subscribersCount],
  ];
  for (const [label, n] of sections) {
    for (const count of doc.querySelectorAll(`[aria-label='${label}'] .b-profile__sections__count`)) {
      if (num(n)) setText(doc, count, formatCount(n));
      else {
        const item = count.closest(".b-profile__sections__item");
        if (item) setAttr(doc, item, "style", "display:none");
      }
    }
  }
  for (const tab of doc.querySelectorAll(".b-tabs__nav__text")) {
    const w = words(tab);
    if (w === "Posts" && num(u.postsCount)) setText(doc, tab, ` ${u.postsCount} post${u.postsCount === 1 ? "" : "s"} `);
    if (w === "Media" && num(u.mediasCount)) setText(doc, tab, ` ${u.mediasCount} Media `);
  }
  const kinds: [string, string, unknown][] = [
    ["all", "All", u.mediasCount],
    ["photo", "Photo", u.photosCount],
    ["video", "Video", u.videosCount],
  ];
  for (const [kind, word, n] of kinds) {
    const text = doc.querySelector(`[data-oi-media-tab='${kind}'] .b-tabs__nav__text`);
    if (text && num(n)) setText(doc, text, ` ${word} ${n} `);
  }

  const all = [...doc.querySelectorAll("[at-attr='profile_label']")].find((t) => words(t) === "All");
  if (all && num(u.postsCount)) setText(doc, all, ` All ${u.postsCount} `);
  const tpl = doc.querySelector<HTMLElement>("[data-oi-template='label']");
  if (tpl?.parentElement) {
    const tabs: [string, number][] = [];
    if (num(u.archivedPostsCount) && u.archivedPostsCount > 0) tabs.push(["Archive", u.archivedPostsCount]);
    if (num(u.privateArchivedPostsCount) && u.privateArchivedPostsCount > 0) tabs.push(["Private Archive", u.privateArchivedPostsCount]);
    for (const l of p.labels ?? []) if (!SYSTEM_LABELS.has(String(l.id)) && l.name) tabs.push([l.name, l.postsCount ?? 0]);
    const clones = tabs.map(([name, n]) => {
      const el = make(tpl);
      el.style.removeProperty("display");
      const text = el.querySelector("[at-attr='profile_label']");
      if (text) text.textContent = ` ${name} ${n} `;
      return el;
    });
    if (clones.length) fill(doc, [tpl], clones, [tpl.parentElement]);
  }

  const create = [...doc.querySelectorAll<HTMLElement>(".stories-list .b-story-item.m-create")].find((t) => words(t) === "Create highlight");
  const strip = create?.parentElement;
  if (!create || !strip) return;
  for (const h of p.highlights ?? []) {
    const el = make(create);
    el.removeAttribute("data-index");
    el.removeAttribute("disabled");
    el.removeAttribute("title");
    el.classList.replace("m-create", "m-gradient-overlay");
    el.querySelector(".b-story-item__icon")?.remove();
    el.dataset.oiHighlight = String(h.id);
    const inside = el.querySelector(".b-story-item__inside");
    inside?.classList.add("m-default-bg");
    const text = el.querySelector(".b-story-item__text");
    if (text) text.textContent = ` ${h.title ?? ""} `;
    if (h.cover && inside) {
      const pic = doc.createElement("img");
      const cover = img(h.cover);
      pic.src = cover;
      pic.alt = "";
      inside.append(pic);
      el.dataset.oiFull = cover;
      el.dataset.oiType = "photo";
    }
    strip.append(el);
    track(doc, () => el.remove());
  }
}

export function newestFirst(posts: MirrorPost[]): MirrorPost[] {
  const merged = [...new Map(posts.map((p) => [String(p.id), p])).values()];
  return merged.sort((a, b) => (valid(b.postedAt)?.getTime() ?? 0) - (valid(a.postedAt)?.getTime() ?? 0));
}

export function applyRecent(doc: Document, posts: MirrorPost[], img: (u: string) => string) {
  const section = doc.querySelector<HTMLElement>("[data-oi-recent]");
  const tpl = section?.querySelector<HTMLElement>(".m-recent-list a[at-attr='photo_item']");
  if (!section || !tpl?.parentElement) return;
  const tiles = newestFirst(posts)
    .map((p) => stillUrl(p.media?.[0]))
    .filter((u): u is string => !!u)
    .slice(0, 3)
    .map((still) => {
      const el = make(tpl);
      delete el.dataset.oiData;
      el.style.removeProperty("display");
      el.querySelector("img.b-photos__item__img")?.setAttribute("src", img(still));
      return el;
    });
  if (!tiles.length) return;
  fill(doc, [tpl], tiles, [tpl.parentElement]);
  setAttr(doc, section, "style", null);
}

export function applyProfileStatus(doc: Document, error: string | null) {
  const text = doc.querySelector<HTMLElement>(".user_posts [data-oi-empty] > span");
  if (!text) return;
  const style = text.getAttribute("style");
  setText(doc, text, error === null ? "Loading posts…" : `Could not load posts: ${error}`);
  track(doc, () => (style === null ? text.removeAttribute("style") : text.setAttribute("style", style)));
  if (error !== null) text.style.color = "#ff4545";
}

export const mediaKind = (doc: Document) => doc.documentElement.dataset.oiMediaType ?? "all";

export const ofKind = (posts: MediaPost[], kind: string) => (kind === "photo" || kind === "video" ? posts.filter((p) => p._kind === kind) : posts);

export interface ProfileHandlers {
  username: string | null;
  visible?: boolean;
  setVisible?: ((on: boolean) => Promise<unknown>) | null;
  read: ((path: string) => Promise<unknown>) | null;
  img: (u: string) => string;
}

export const ARCHIVE_PATH = "/api/of/v2/stories/archive?limit=20";
const STATUS_ROWS = [
  { value: "true", label: "Available" },
  { value: "false", label: "Invisible" },
];
const ARCHIVE_BOX = "[data-oi-story-archive-box]";

const day = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

function openArchive(doc: Document, tile: HTMLElement, h: ProfileHandlers) {
  const strip = tile.closest(".stories-list") ?? tile;
  const box = doc.createElement("div");
  box.setAttribute("data-oi-story-archive-box", "");
  box.setAttribute("data-oi-wired", "");
  box.style.cssText = "display:flex;flex-wrap:wrap;gap:8px;padding:8px 16px 16px;";
  const line = (text: string, error = false) => {
    const p = doc.createElement("div");
    p.className = "g-gray-text";
    p.style.cssText = `width:100%;padding:8px 0;${error ? "color:#ff4545;" : ""}`;
    p.textContent = text;
    box.replaceChildren(p);
  };
  strip.after(box);
  tile.setAttribute("aria-expanded", "true");
  if (!h.read) return line("Select a model to see its story archive");
  line("Loading…");
  h.read(ARCHIVE_PATH).then(
    (r) => {
      if (!box.isConnected) return;
      const list = Array.isArray(r) ? r : Array.isArray((r as { list?: unknown })?.list) ? (r as { list: unknown[] }).list : null;
      if (!list) return line("Could not load the story archive: unexpected response", true);
      if (!list.length) return line("Nothing found");
      box.replaceChildren(
        ...list.map((s) => {
          const story = s as { id?: unknown; createdAt?: string; media?: MirrorPost["media"] };
          const el = doc.createElement("div");
          el.className = "b-story-item m-default-bg";
          el.style.cssText = "width:96px;height:150px;border-radius:8px;overflow:hidden;position:relative;background:#8a96a3;";
          const still = stillUrl(story.media?.[0]);
          if (still) {
            const pic = doc.createElement("img");
            pic.src = h.img(still);
            pic.alt = "";
            pic.style.cssText = "width:100%;height:100%;object-fit:cover;";
            el.append(pic);
          }
          const at = valid(story.createdAt);
          if (at) {
            const date = doc.createElement("span");
            date.textContent = day(at);
            date.style.cssText = "position:absolute;left:6px;bottom:6px;color:#fff;font-size:12px;text-shadow:0 0 3px #000;";
            el.append(date);
          }
          return el;
        }),
      );
    },
    (e) => box.isConnected && line(`Could not load the story archive: ${message(e)}`, true),
  );
}

export const STICKY_HEADER_PX = 180;

function stickHeader(doc: Document): void {
  const header = doc.querySelector(".js-compact-sticky-header");
  const on = (doc.defaultView?.scrollY ?? 0) > STICKY_HEADER_PX;
  if (!header || header.classList.contains("m-sticky") === on) return;
  header.classList.toggle("m-sticky", on);
  const back = header.querySelector(".g-page__header__btn");
  back?.classList.toggle("m-default-color", on);
  back?.classList.toggle("m-white", !on);
  back?.classList.toggle("m-light", !on);
  const more = header.querySelector(".b-compact-header__settings .dropdown-toggle");
  more?.classList.toggle("m-dark", on);
  more?.classList.toggle("m-light", !on);
  const sections = header.querySelector(".b-profile__sections");
  sections?.classList.toggle("d-flex", !on);
  sections?.classList.toggle("align-items-center", !on);
  for (const el of header.querySelectorAll<HTMLElement>("[data-oi-sticky-only]")) el.style.display = on ? "" : "none";
}

export function bindProfile(doc: Document, h: ProfileHandlers): () => void {
  const status = doc.querySelector<HTMLElement>("[data-oi-user-status]");
  let visible = h.visible ?? true;
  const showStatus = (on: boolean) => {
    const text = status && [...status.childNodes].find((n) => n.nodeType === 3 && n.nodeValue?.trim());
    if (text) text.nodeValue = ` ${STATUS_ROWS.find((r) => r.value === String(on))!.label} `;
  };
  if (typeof h.visible === "boolean") showStatus(h.visible);
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    const st = t.closest<HTMLElement>("[data-oi-user-status]");
    if (st) {
      ev.preventDefault();
      if (!h.setVisible) return note(doc, st, SELECT_MODEL);
      const save = h.setVisible;
      showMenu(doc, st, [{ name: "status", options: STATUS_ROWS, value: String(visible) }], (_, v) => {
        const was = visible;
        visible = v === "true";
        if (visible === was) return;
        showStatus(visible);
        save(visible).catch((e) => {
          visible = was;
          showStatus(was);
          note(doc, st, `Could not change the status: ${message(e)}`, true);
        });
      });
      return;
    }
    const archive = t.closest<HTMLElement>("[data-oi-story-archive]");
    if (archive) {
      ev.preventDefault();
      const box = doc.querySelector(ARCHIVE_BOX);
      if (box) {
        box.remove();
        archive.setAttribute("aria-expanded", "false");
      } else openArchive(doc, archive, h);
      return;
    }
    const copy = t.closest<HTMLElement>("[data-oi-copy-link]");
    if (copy) {
      ev.preventDefault();
      if (!h.username) return note(doc, copy, "Select a model to copy its link");
      const clipboard = doc.defaultView?.navigator.clipboard;
      if (!clipboard) return note(doc, copy, "Could not copy the link", true);
      clipboard.writeText(`https://onlyfans.com/${h.username}`).then(
        () => void toast(doc, "Link copied"),
        () => note(doc, copy, "Could not copy the link", true),
      );
      return;
    }
    const bio = t.closest<HTMLElement>("[data-oi-bio-toggle]");
    if (bio) {
      ev.preventDefault();
      foldBio(bio, bio.parentElement?.querySelector<HTMLElement>(".g-truncated-text"), bio.getAttribute("aria-expanded") !== "true");
      return;
    }
    const collapse = t.closest<HTMLElement>("[data-oi-collapse]");
    if (collapse) {
      ev.preventDefault();
      const item = collapse.parentElement;
      const content = collapse.nextElementSibling as HTMLElement | null;
      const open = !item?.classList.contains("m-active");
      item?.classList.toggle("m-active", open);
      collapse.setAttribute("aria-expanded", String(open));
      if (content) content.style.display = open ? "" : "none";
      return;
    }
    const tab = t.closest<HTMLElement>("[data-oi-media-tab]");
    if (tab) {
      ev.preventDefault();
      for (const other of doc.querySelectorAll("[data-oi-media-tab]")) other.classList.toggle("m-current", other === tab);
      doc.documentElement.dataset.oiMediaType = tab.dataset.oiMediaTab!;
      doc.dispatchEvent(new Event(PROFILE_CHANGE));
    }
  };
  doc.addEventListener("click", onClick, true);
  const fit = () => fitBio(doc);
  fit();
  const RO = doc.defaultView?.ResizeObserver;
  const ro = RO ? new RO(fit) : null;
  for (const el of doc.querySelectorAll(".b-user-info .b-user-info__text")) ro?.observe(el);
  const win = doc.defaultView;
  const stick = () => stickHeader(doc);
  stick();
  win?.addEventListener("scroll", stick, { passive: true });
  return () => {
    doc.removeEventListener("click", onClick, true);
    win?.removeEventListener("scroll", stick);
    ro?.disconnect();
  };
}

export function useOfProfile(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const me = useQuery(ofMeQuery(accountId)).data;
  const username = me?.username ?? null;
  const visible = me?.isVisibleOnline;
  const qc = useQueryClient();
  const mine = PROFILE_SRC.test(src);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !mine) return;
    const h: ProfileHandlers = {
      username: accountId ? username : null,
      visible: accountId ? visible : undefined,
      setVisible: accountId
        ? (on) => relay.patch("/api/of/v2/users/me", { isVisibleOnline: on }, { accountId }).then(() => qc.invalidateQueries({ queryKey: ofMeQuery(accountId).queryKey }))
        : null,
      read: accountId ? (path) => relay.get(path, { accountId }) : null,
      img: (u) => proxyImage(u, accountId),
    };
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      unbind = doc?.body ? bindProfile(doc, h) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, mine, accountId, username, visible, qc]);
}
