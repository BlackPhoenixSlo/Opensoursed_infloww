import type { PickedGif } from "@/components/chat/GifPicker";
import { templateMediaToVault, type PickedTemplate } from "@/components/chat/TemplatePicker";
import type { TaggedCreatorChoice, VaultMedia } from "@/lib/relay";
import { hasOfFormatting } from "@/lib/ofRichText";
import { richMode, type RichMode } from "@/lib/ofRichMode";

export interface ComposeDraft {
  text?: string;
  attached: VaultMedia[];
  price: string;
  previewCount: number;
  taggedCreators: TaggedCreatorChoice[];
  lockedText?: boolean;
  pickedGifs?: PickedGif[];
}

export type TextBoxAction = { type: "pickTemplate"; t: PickedTemplate; rich: boolean } | { type: "aa" };

export function textBoxReducer<D extends ComposeDraft & { text: string; mode: RichMode }>(s: D, a: TextBoxAction): D {
  if (a.type === "aa") return { ...s, mode: richMode(s.mode, { type: "aa", formatted: hasOfFormatting(s.text) }) };
  const n = applyTemplate(s, a.t, a.rich);
  return { ...n, mode: richMode(s.mode, { type: "loaded", formatted: hasOfFormatting(n.text), allowed: a.rich }) };
}

function mergeTags(prev: TaggedCreatorChoice[], ids: number[]): TaggedCreatorChoice[] {
  if (!ids.length) return prev;
  const have = new Set(prev.map((c) => c.id));
  const additions = ids
    .filter((id) => !have.has(id))
    .map((id): TaggedCreatorChoice => ({ id, name: `user${id}`, username: "", avatar: null }));
  return additions.length ? [...prev, ...additions] : prev;
}

export function templateText(t: Pick<PickedTemplate, "text" | "displayText">, rich: boolean): string {
  return rich && hasOfFormatting(t.displayText) ? t.displayText.trim() : t.text;
}

export function applyTemplate<D extends ComposeDraft>(draft: D, t: PickedTemplate, rich = false): D {
  // Snapshot: a FREE template must clear a typed price, or it goes out as a stale PPV (price > 0 is the sole paid signal).
  const paid = t.price > 0;
  const next: D = {
    ...draft,
    attached: templateMediaToVault(t),
    price: paid ? String(t.price) : "",
    previewCount: t.previews.length,
    taggedCreators: mergeTags(draft.taggedCreators, t.taggedUsers),
  };
  if (draft.text !== undefined) next.text = templateText(t, rich);
  if (draft.lockedText !== undefined) next.lockedText = paid ? t.lockedText : false;
  if (draft.pickedGifs !== undefined) {
    const url = t.gifUrl ?? "";
    next.pickedGifs = t.gifId ? [{ id: t.gifId, thumbUrl: url, fullUrl: url, title: t.title }] : draft.pickedGifs;
  }
  return next;
}

export function canBeFreePreview(m: Pick<VaultMedia, "id" | "_claim">): boolean {
  // A fresh upload (_claim) has no vault id yet: it can't be referenced in previews, so OF would lock it.
  return !m._claim && Number.isFinite(m.id) && m.id > 0;
}

export function wireMedia(m: VaultMedia): number | Record<string, unknown> {
  return m._claim ?? m.id;
}

export function previewIdsFor(media: readonly VaultMedia[], count: number, price: number): number[] {
  if (!(price > 0) || count <= 0) return [];
  return media.slice(0, count).filter(canBeFreePreview).map((m) => m.id);
}
