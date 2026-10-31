/**
 * composeDraft — pure draft rules shared by the composers (MassMessageComposer,
 * PostComposer, and the chat Composer's draft in chat/composerDraft).
 *
 *   • `applyTemplate`: a template is a SNAPSHOT. Text, attachments and the
 *     preview count are replaced wholesale (the leading N tiles = free, so a
 *     merge would break the saved FREE-first order). The price is replaced
 *     too: a FREE template clears a typed price and the text lock, or a "free"
 *     template would go out as a stale PPV (a price > 0 is the sole paid
 *     signal). A template without a GIF clears picked GIFs, so a stale pick
 *     doesn't ride along. Tagged creators are merged (placeholders by id).
 *     Fields a composer lacks (`lockedText`, `pickedGifs` on a post; `text`
 *     in the chat draft, whose text is the chat's own) are left absent.
 *   • `canBeFreePreview` is THE free-preview rule: only a tile with a real
 *     vault id can be a free teaser. A fresh upload still carries a `_claim`
 *     (no id until OF resolves it): it rides as media but can't be referenced
 *     in `previews`, so OF locks it. `previewIdsFor` (the wire) and MediaTray's
 *     FREE badge both read it, so the tray never promises a teaser the send
 *     drops. Free sends carry no previews.
 */

import type { PickedGif } from "@/components/chat/GifPicker";
import { templateMediaToVault, type PickedTemplate } from "@/components/chat/TemplatePicker";
import type { TaggedCreatorChoice, VaultMedia } from "@/lib/relay";

export interface ComposeDraft {
  /** Absent on a draft whose text lives elsewhere (the chat's `useChatDraft`). */
  text?: string;
  attached: VaultMedia[];
  /** The price input, "" = free. */
  price: string;
  previewCount: number;
  taggedCreators: TaggedCreatorChoice[];
  /** Absent on a composer without a lock-text option. */
  lockedText?: boolean;
  /** Absent on a composer without a GIF picker. */
  pickedGifs?: PickedGif[];
}

/** `prev` plus a placeholder chip per tagged id it lacks (the picker resolves
 *  names lazily; the template only has ids). */
function mergeTags(prev: TaggedCreatorChoice[], ids: number[]): TaggedCreatorChoice[] {
  if (!ids.length) return prev;
  const have = new Set(prev.map((c) => c.id));
  const additions = ids
    .filter((id) => !have.has(id))
    .map((id): TaggedCreatorChoice => ({ id, name: `user${id}`, username: "", avatar: null }));
  return additions.length ? [...prev, ...additions] : prev;
}

/** The draft with template `t` applied (see the file header). */
export function applyTemplate<D extends ComposeDraft>(draft: D, t: PickedTemplate): D {
  const paid = t.price > 0;
  const next: D = {
    ...draft,
    attached: templateMediaToVault(t),
    price: paid ? String(t.price) : "",
    previewCount: t.previews.length,
    taggedCreators: mergeTags(draft.taggedCreators, t.taggedUsers),
  };
  if (draft.text !== undefined) next.text = t.text;
  if (draft.lockedText !== undefined) next.lockedText = paid ? t.lockedText : false;
  if (draft.pickedGifs !== undefined) {
    const url = t.gifUrl ?? "";
    next.pickedGifs = t.gifId ? [{ id: t.gifId, thumbUrl: url, fullUrl: url, title: t.title }] : [];
  }
  return next;
}

/** Whether a tile can be a free preview (see the file header). */
export function canBeFreePreview(m: Pick<VaultMedia, "id" | "_claim">): boolean {
  return !m._claim && Number.isFinite(m.id) && m.id > 0;
}

/** A tile on the wire: its upload claim, else its vault id. */
export function wireMedia(m: VaultMedia): number | Record<string, unknown> {
  return m._claim ?? m.id;
}

/** The free-preview vault ids of a send of `media` (the tiles it sends):
 *  the leading `count` that can be previews, none on a free send. */
export function previewIdsFor(media: readonly VaultMedia[], count: number, price: number): number[] {
  if (!(price > 0) || count <= 0) return [];
  return media.slice(0, count).filter(canBeFreePreview).map((m) => m.id);
}
