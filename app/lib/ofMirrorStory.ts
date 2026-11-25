"use client";


import { useEffect, useMemo, type RefObject } from "react";
import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { relay, type VaultMedia } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { rowsOf } from "@/lib/ofMirrorData";
import { openViewer, viewerItem, type StoryAuthor, type ViewerItem } from "@/lib/ofMirrorVault";
import { message, note, READ_ONLY, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { storyItems, type StoryEntry } from "@/lib/ofMirrorFeedsStrip";

export type VaultStoryBody = { media_url: string } | { media_files: number[] };
export function vaultStoryBody(id: number, items: VaultMedia[] | undefined): VaultStoryBody {
  const m = items?.find((v) => Number(v.id) === id);
  const url = m?.type === "photo" ? m.files?.full?.url : undefined;
  return url ? { media_url: url } : { media_files: [id] };
}

const OWN_STORIES = /^\/api\/of\/v2\/users\/[^/]+\/stories$/;
const refetchOwnStories = (qc: QueryClient, accountId: string | null) =>
  void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === "of-mirror-data" && q.queryKey[1] === accountId && OWN_STORIES.test(String(q.queryKey[2])) });

export const STORY_PICK = "image/*,video/*";
export const NOT_STORY_MEDIA = "Could not add: choose an image or a video";

export const STORY = {
  own: ".b-story-item.m-story-item-own",
  tile: ".b-story-item",
  viewable: "[data-oi-story-user], [data-oi-story], [data-oi-highlight], [data-oi-full]",
  strip: ".stories-list",
};

export interface StoryHandlers {
  addStory(file: File): Promise<unknown>;
  userStories?(userId: string): Promise<ViewerItem[]>;
  highlightStories?(highlightId: string): Promise<ViewerItem[]>;
}

function tileAuthor(tile: HTMLElement): StoryAuthor {
  const name = tile.querySelector(".b-story-item__text")?.textContent?.trim() || tile.title.trim();
  const pic = tile.querySelector(".b-story-item__icon img") ?? tile.querySelector(".b-story-item__inside > img");
  return { name, avatar: pic?.getAttribute("src") ?? null };
}

export function highlightItems(r: unknown, img: (u: string) => string): ViewerItem[] {
  const stories = (r as { stories?: unknown } | null)?.stories;
  return Array.isArray(stories) ? storyItems(stories as StoryEntry[], img) : [];
}

function tileItems(tile: HTMLElement): ViewerItem[] {
  if (tile.dataset.oiStory) {
    try {
      const items = JSON.parse(tile.dataset.oiStory) as ViewerItem[];
      if (Array.isArray(items) && items.length) return items;
    } catch { }
  }
  const one = viewerItem(tile);
  return one ? [one] : [];
}

export function bindStory(doc: Document, handlers: StoryHandlers | null): () => void {
  const strip = doc.querySelector(STORY.strip);
  if (!strip) return () => {};
  const viewStory = (tile: HTMLElement) => {
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
    const file = input.files?.[0];
    if (!file || !handlers) return;
    if (!/^(image|video)\//.test(file.type)) return note(doc, strip, NOT_STORY_MEDIA, true);
    // Disabled while uploading: no second picker, no second Story.
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

export { refetchOwnStories };
