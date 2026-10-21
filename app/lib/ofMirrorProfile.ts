"use client";

/**
 * My profile on the OF mirror (profile/index, profile/media, profile/state-more-menu; the generator's profilePage keeps
 * no example there). ofMirrorData's Part "profile" draws, from the Creator's /users/me, its highlights and its post
 * labels: the compact header's Photos, Videos, Likes and Fans counts, the Posts and Media tabs' counts, the wall's label
 * tabs (All, Archive and Private Archive when it has some, then each label; only All is open, as the Relay's posts route
 * has no label filter) and the Media tab's All, Photo and Video counts, and appends a tile per highlight to the story
 * strip (its cover and title; a click opens the cover in the Vault's viewer, ofMirrorPost's bindStory: the Relay reads no
 * highlight's own stories). applyRecent fills the sidebar's Recent strip with the
 * Creator's three newest media posts. bindProfile works the page's own controls in place: Story archive opens a box
 * under the strip with the Creator's archived stories (GET /stories/archive), Copy link to profile copies
 * https://onlyfans.com/<username>, More info and Spotify's title collapse and expand, and the Media tab's All, Photo
 * and Video filter the grid (PROFILE_CHANGE: ofMirrorData redraws it). In All models the page shows the first model
 * (standInModel), never the generator's placeholders; so do Statements' Earnings and Release forms.
 */

import { useEffect, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { useUser } from "@/contexts/UserContext";
import { useAccounts, useActiveAccounts } from "@/hooks/useAccounts";
import { relay } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { stillUrl } from "@/lib/ofMedia";
import { fill, make, setAttr, setText, track, valid, type PostLabel } from "@/lib/ofMirrorData";
import type { MirrorPost } from "@/lib/ofMirrorFeeds";
import { formatCount, ofMeQuery } from "@/lib/ofMirrorIdentity";
import { message, note } from "@/lib/ofMirrorWrites";

/** My profile's pages (profile/index, profile/media, profile/state-*). */
const PROFILE_SRC = /^\/of-mirror\/pages\/profile\//;
/**
 * The pages that show one model in All models, so never placeholders: My profile's, the avatar menu, the Messages
 * tab's (its chats, a chat, New message), the Queue's, Statements' Earnings (statements/index: its default tab), New
 * post's (new-post/index, new-post/state-*), every Statistics tab, the Vault's (vault/index, vault/list, vault/state-*) and
 * every Settings page (settings/*: its values, rows and saves).
 */
const STAND_IN_SRC = /^\/of-mirror\/pages\/(?:profile\/|release-forms\/|messages\/|queue\/|new-post\/|statistics\/|vault\/|settings\/|home\/state-avatar-menu\.html|statements\/(?:index|earnings)\.html$)/;

/**
 * The model My profile, the avatar menu, Messages, the Queue, Statements' Earnings, New post, Statistics, the Vault and
 * Settings show in All models: the first model with a session (`accounts` in the picker's order), so the page is that model's real
 * profile, menu, chats, scheduled items, earnings, composer, figures or vault rather than placeholders, and its actions
 * (New post's Post too) are that model's. null: a model is selected, the page is none of them, or there is no model.
 */
export function standInModel(src: string, accountId: string | null, accounts: readonly { id: string }[]): string | null {
  return !accountId && STAND_IN_SRC.test(src) ? (accounts[0]?.id ?? null) : null;
}

/** The model each principal's frames last stood in with (a frame remounts per page, so this outlives it). */
const lastStandIn = new Map<string, string>();

/**
 * standInModel for a frame, the model list read here. A list with no answer (loading, its cache dropped) or an empty
 * answer keeps the model the frame last stood in with: without it the page binds with no model (New message back from
 * its vault: no draft, no status line, the vault's ticks kept) and stays so until the list is read again. A list that
 * names models but none with a session is an answer: no model.
 */
export function useStandIn(src: string): string | null {
  const { accountId } = useScope();
  const principal = useUser().user?.user_id ?? "";
  const accounts = useAccounts().data?.accounts;
  const standIn = standInModel(src, accountId, useActiveAccounts());
  useEffect(() => {
    if (standIn) lastStandIn.set(principal, standIn);
  }, [principal, standIn]);
  if (standIn || accountId || !STAND_IN_SRC.test(src) || accounts?.length) return standIn;
  return lastStandIn.get(principal) ?? null;
}

/** The Media tab's type filter changed (bindProfile): ofMirrorData redraws the grid. */
export const PROFILE_CHANGE = "oi-profile-change";

/** /users/me's counts My profile shows (OF's own field names). */
export interface ProfileUser {
  postsCount?: number | null;
  mediasCount?: number | null;
  photosCount?: number | null;
  videosCount?: number | null;
  /** Likes. */
  favoritedCount?: number | null;
  /** Fans; OF sends none when the Creator hides it. */
  subscribersCount?: number | null;
  archivedPostsCount?: number | null;
  privateArchivedPostsCount?: number | null;
}

/** A story highlight, as /users/{id}/stories/highlights lists it. */
export interface Highlight {
  id: number | string;
  title?: string | null;
  /** Its cover picture's URL. */
  cover?: string | null;
  storiesCount?: number | null;
}

export interface MirrorProfile {
  user: ProfileUser;
  labels?: PostLabel[];
  highlights?: Highlight[];
}

/** A media grid post, tagged by the route it came from (/posts/photos or /posts/videos). */
export type MediaPost = MirrorPost & { _kind?: "photo" | "video" };

const num = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const words = (el: Element) => (el.textContent ?? "").replace(/\s+/g, " ").trim();
const SYSTEM_LABELS = new Set(["archived", "private_archived"]);

/** The counts, label tabs and highlights of My profile (see the module comment). */
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

  // The wall's label tabs: All's count, then a copy of the hidden tab per label with posts.
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

  // A tile per highlight, after the strip's own: a copy of Create highlight, its cover viewable (`data-oi-full`).
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

/** Merged by post id, newest first (a post with both photos and videos is in both routes). */
export function newestFirst(posts: MirrorPost[]): MirrorPost[] {
  const merged = [...new Map(posts.map((p) => [String(p.id), p])).values()];
  return merged.sort((a, b) => (valid(b.postedAt)?.getTime() ?? 0) - (valid(a.postedAt)?.getTime() ?? 0));
}

/** The sidebar's Recent strip: the three newest media posts with a picture, in copies of its hidden tile; none: it stays hidden. */
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

/**
 * The wall's or the Media grid's "No posts yet" before its rows are here: "Loading posts…" (`error` null), or the red
 * "Could not load posts: <the Relay's text>".
 */
export function applyProfileStatus(doc: Document, error: string | null) {
  const text = doc.querySelector<HTMLElement>(".user_posts [data-oi-empty] > span");
  if (!text) return;
  const style = text.getAttribute("style");
  setText(doc, text, error === null ? "Loading posts…" : `Could not load posts: ${error}`);
  track(doc, () => (style === null ? text.removeAttribute("style") : text.setAttribute("style", style)));
  if (error !== null) text.style.color = "#ff4545";
}

/** The Media tab's type filter: "all" (or none), "photo", "video". Kept on the frame's root, so a redraw keeps it. */
export const mediaKind = (doc: Document) => doc.documentElement.dataset.oiMediaType ?? "all";

/** The posts the Media tab's open filter shows. */
export const ofKind = (posts: MediaPost[], kind: string) => (kind === "photo" || kind === "video" ? posts.filter((p) => p._kind === kind) : posts);

export interface ProfileHandlers {
  /** The Creator's OF username (Copy link to profile); null in All Creators. */
  username: string | null;
  /** GET a Relay path; null in All Creators. */
  read: ((path: string) => Promise<unknown>) | null;
  img: (u: string) => string;
}

export const ARCHIVE_PATH = "/api/of/v2/stories/archive?limit=20";
const ARCHIVE_BOX = "[data-oi-story-archive-box]";

/** A story's date: OF's "Oct 3, 2026". */
const day = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

/** The Story archive box under the strip: loading, then the archived stories as tiles (picture, date), else OF's "Nothing found". */
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

/** Bind My profile's in-place controls on `doc` (see the module comment). Returns an unbind. */
export function bindProfile(doc: Document, h: ProfileHandlers): () => void {
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
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
        () => note(doc, copy, "Link copied"),
        () => note(doc, copy, "Could not copy the link", true),
      );
      return;
    }
    const bio = t.closest<HTMLElement>("[data-oi-bio-toggle]");
    if (bio) {
      ev.preventDefault();
      const text = bio.parentElement?.querySelector<HTMLElement>(".g-truncated-text");
      const open = bio.getAttribute("aria-expanded") === "true";
      bio.setAttribute("aria-expanded", String(!open));
      bio.textContent = open ? " More info " : " Collapse info ";
      if (text) {
        text.classList.toggle("m-collapsed", open);
        if (open) text.style.maxHeight = text.dataset.oiMaxHeight ?? "";
        else {
          text.dataset.oiMaxHeight = text.style.maxHeight;
          text.style.maxHeight = "none";
        }
      }
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
  return () => doc.removeEventListener("click", onClick, true);
}

/** My profile's pages: bind its in-place controls on every frame load (the archive and the link need a single model). */
export function useOfProfile(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const username = useQuery(ofMeQuery(accountId)).data?.username ?? null;
  const mine = PROFILE_SRC.test(src);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !mine) return;
    const h: ProfileHandlers = {
      username: accountId ? username : null,
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
  }, [frameRef, src, mine, accountId, username]);
}
