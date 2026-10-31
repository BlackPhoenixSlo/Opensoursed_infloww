"use client";

/**
 * OF's story strip on every Mirror page (bindStory, useOfStory: view a tile's stories, Add to story) and a vault item as
 * a Story (vaultStoryBody). ofMirrorPost re-exports its public names.
 */

import { useEffect, useMemo, type RefObject } from "react";
import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { relay, type VaultMedia } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { rowsOf } from "@/lib/ofMirrorData";
import { openViewer, viewerItem, type StoryAuthor, type ViewerItem } from "@/lib/ofMirrorVault";
import { message, note, READ_ONLY, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { storyItems, type StoryEntry } from "@/lib/ofMirrorFeeds";

/**
 * POST /api/of/v2/stories for one vault item, as OF's web client publishes a vault item as a Story: a photo by its full
 * picture (`media_url`; the Relay fetches and re-uploads it, as OF's `addStoryFromVault` does), anything else (or a
 * photo the list does not hold with a full url) by its vault id (`media_files`, OF's `createStoryByFileId`).
 */
export type VaultStoryBody = { media_url: string } | { media_files: number[] };
export function vaultStoryBody(id: number, items: VaultMedia[] | undefined): VaultStoryBody {
  const m = items?.find((v) => Number(v.id) === id);
  const url = m?.type === "photo" ? m.files?.full?.url : undefined;
  return url ? { media_url: url } : { media_files: [id] };
}

/** A Creator's active stories read (ofMirrorData's Home strip: GET /users/{id}/stories). */
const OWN_STORIES = /^\/api\/of\/v2\/users\/[^/]+\/stories$/;
/** A story was added: the Creator's own stories are read again, so it shows in Home's strip. */
const refetchOwnStories = (qc: QueryClient, accountId: string | null) =>
  void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === "of-mirror-data" && q.queryKey[1] === accountId && OWN_STORIES.test(String(q.queryKey[2])) });

/** What Add to story takes: an image or a video (OF's stories take both), and its note for anything else. */
export const STORY_PICK = "image/*,video/*";
export const NOT_STORY_MEDIA = "Could not add: choose an image or a video";

/** OF's story strip: its own "Add to story" tile, any tile, a tile with media to view (a creator's stories on Home, a
 *  highlight on My profile) and the strip (the note's anchor, outside the scroller's views). */
export const STORY = {
  own: ".b-story-item.m-story-item-own",
  tile: ".b-story-item",
  viewable: "[data-oi-story-user], [data-oi-story], [data-oi-highlight], [data-oi-full]",
  strip: ".stories-list",
};

export interface StoryHandlers {
  addStory(file: File): Promise<unknown>;
  /** A creator's current stories, as viewer items (GET /users/{id}/stories). */
  userStories?(userId: string): Promise<ViewerItem[]>;
  /** A highlight's stories in order, as viewer items (GET /stories/highlights/{id}). */
  highlightStories?(highlightId: string): Promise<ViewerItem[]>;
}

/** A story tile's header in the story player: its name (a creator's, a highlight's title) and its avatar, else its picture. */
function tileAuthor(tile: HTMLElement): StoryAuthor {
  const name = tile.querySelector(".b-story-item__text")?.textContent?.trim() || tile.title.trim();
  const pic = tile.querySelector(".b-story-item__icon img") ?? tile.querySelector(".b-story-item__inside > img");
  return { name, avatar: pic?.getAttribute("src") ?? null };
}

/** A highlight's viewer items from OF's GET /stories/highlights/{id} answer (`{..., stories: [...]}`, read from OF's app.js:
 *  unconfirmed against a real account); anything else: none. */
export function highlightItems(r: unknown, img: (u: string) => string): ViewerItem[] {
  const stories = (r as { stories?: unknown } | null)?.stories;
  return Array.isArray(stories) ? storyItems(stories as StoryEntry[], img) : [];
}

/** What a viewable tile shows without a read: its stories (`data-oi-story`), else its own file (`data-oi-full`). */
function tileItems(tile: HTMLElement): ViewerItem[] {
  if (tile.dataset.oiStory) {
    try {
      const items = JSON.parse(tile.dataset.oiStory) as ViewerItem[];
      if (Array.isArray(items) && items.length) return items;
    } catch { /* fall through */ }
  }
  const one = viewerItem(tile);
  return one ? [one] : [];
}

/**
 * Wire OF's story strip in `doc` (any Mirror page; a page without the strip is left alone). A viewable tile (STORY.viewable)
 * plays its media in the Vault's viewer as OF's story player (openViewer's story mode, the tile's name and avatar in its
 * header; previous / next through a creator's stories): the stories the feed carried,
 * else the creator's current stories read through `handlers.userStories` (a failure or none: a note under the strip).
 * A highlight tile (`data-oi-highlight`) plays the highlight's stories in order, read through `handlers.highlightStories`
 * (a failure or none: a note); with no such handler, its cover. Every other tile but "Add to story" ("Go live", "Create highlight", ...) sends nothing and shows the Read-only note under the strip,
 * in either scope (bindWrites' click fallback leaves them to this, as its note would sit inside the scroller). These tiles are not marked
 * `data-oi-wired`. A strip without "Add to story" (My profile's) gets nothing more. "Add to story": a click opens a
 * hidden image picker appended to the body; a picked file goes to `handlers.addStory`, then "Added to story" shows
 * under the strip. While it uploads the tile is disabled (no second picker, no second Story) and a stale note is gone;
 * a failure shows a red "Could not add: …" that stays. Either way the tile is enabled again and the picker cleared, so
 * the same file can be picked again. A non-image pick (or one with no type) sends nothing and shows a red
 * "Could not add: choose an image"; a cancelled picker does nothing. `handlers` null (no single Creator): no picker, the select-a-model note. Returns
 * an unbind, which removes the picker.
 */
export function bindStory(doc: Document, handlers: StoryHandlers | null): () => void {
  const strip = doc.querySelector(STORY.strip);
  if (!strip) return () => {};
  // Not readOnly(panel): it anchors the note on the button (inside the scroller's views) and catches the own tile too.
  const viewStory = (tile: HTMLElement) => {
    // A highlight (My profile) plays its stories, read on each click as OF's fetchHighlightsById; no single Creator: its cover.
    const play = (items: ViewerItem[]) => openViewer(doc, items, 0, tileAuthor(tile));
    const highlight = tile.dataset.oiHighlight;
    if (highlight && handlers?.highlightStories) {
      handlers.highlightStories(highlight).then(
        (got) => (got.length ? play(got) : note(doc, strip, "No story to show", true)),
        (e) => note(doc, strip, `Could not load the highlight: ${message(e)}`, true),
      );
      return;
    }
    const items = tileItems(tile);
    if (items.length) return play(items);
    const user = tile.dataset.oiStoryUser;
    if (!user || !handlers?.userStories) return note(doc, strip, handlers ? "No story to show" : SELECT_MODEL, !!handlers);
    handlers.userStories(user).then(
      (got) => (got.length ? play(got) : note(doc, strip, "No story to show", true)),
      (e) => note(doc, strip, `Could not load the story: ${message(e)}`, true),
    );
  };
  const onOther = (ev: Event) => {
    const tile = (ev.target as Element | null)?.closest?.(STORY.tile);
    if (tile?.matches(STORY.viewable) && !tile.matches(":disabled")) {
      ev.preventDefault();
      return viewStory(tile as HTMLElement);
    }
    // A tile that is a link (New post's Go live), disabled or wired (My profile's Story archive) goes its own way.
    if (!tile || tile.matches(STORY.own) || tile.closest("a[href]") || tile.matches(":disabled, [data-oi-wired]")) return;
    ev.preventDefault();
    note(doc, strip, READ_ONLY);
  };
  strip.addEventListener("click", onOther);
  const own = strip.querySelector<HTMLButtonElement>(STORY.own);
  if (!own) return () => strip.removeEventListener("click", onOther);
  const input = doc.createElement("input");
  input.type = "file";
  input.accept = STORY_PICK;
  input.style.display = "none";
  input.setAttribute("data-oi-wired", "");
  doc.body.append(input);
  own.setAttribute("data-oi-wired", "");

  const onClick = (ev: Event) => {
    ev.preventDefault();
    if (!handlers) note(doc, strip, SELECT_MODEL);
    else if (!own.disabled) input.click();
  };
  const onChange = () => {
    // The File comes from the frame's realm: no `instanceof File` on it.
    const file = input.files?.[0];
    if (!file || !handlers) return;
    if (!/^(image|video)\//.test(file.type)) return note(doc, strip, NOT_STORY_MEDIA, true);
    own.disabled = true;
    doc.getElementById("oi-note")?.remove();
    handlers
      .addStory(file)
      .then(
        () => note(doc, strip, "Added to story"),
        (e) => note(doc, strip, `Could not add: ${message(e)}`, true),
      )
      .finally(() => {
        own.disabled = false;
        input.value = "";
      });
  };
  own.addEventListener("click", onClick);
  input.addEventListener("change", onChange);
  return () => {
    strip.removeEventListener("click", onOther);
    own.removeEventListener("click", onClick);
    input.removeEventListener("change", onChange);
    input.remove();
  };
}

/** Every Mirror page: bind the story strip (bindStory) on every frame load (a Story only with a single Creator). */
export function useOfStory(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const { mutateAsync: addStory } = useMutation({
    mutationFn: (file: File) => relay.uploadFile("/api/of/v2/stories/upload", file, "file", { accountId }),
    onSuccess: () => refetchOwnStories(qc, accountId),
  });

  const userStories = useMemo(
    () => async (userId: string) => {
      const r = await relay.get<unknown>(`/api/of/v2/users/${encodeURIComponent(userId)}/stories`, { accountId });
      return storyItems(rowsOf<StoryEntry>(r) ?? [], (u) => proxyImage(u, accountId));
    },
    [accountId],
  );
  const highlightStories = useMemo(
    () => async (id: string) =>
      highlightItems(await relay.get<unknown>(`/api/of/v2/stories/highlights/${encodeURIComponent(id)}`, { accountId }), (u) => proxyImage(u, accountId)),
    [accountId],
  );

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      unbind = doc?.body ? bindStory(doc, accountId ? { addStory, userStories, highlightStories } : null) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, accountId, addStory, userStories, highlightStories]);
}

/** For ofMirrorPost only; not re-exported. */
export { refetchOwnStories };
