/**
 * Messages Pro scripts from and onto a chat (roadmap W4 4.2):
 *   • `scriptDraftFromMessage` — "Save as script" on one of our bubbles turns
 *     the sent message back into a saved-reply draft (text, media, price,
 *     free previews, GIF).
 *   • `scriptPickWarning` — the "Use script?" guard: what to warn about before
 *     a script lands in the composer for this Fan (media he already bought,
 *     media deleted from the vault). Null when there is nothing to say.
 */

import type { SavedReplyDraft } from "@/hooks/useSavedReplies";
import type { FanVaultEntry } from "@/hooks/useFanVaultHistory";
import type { PickedTemplate } from "@/components/chat/TemplatePicker";
import type { OFMessage } from "@/lib/relay";
import { vaultFilesFromChat } from "@/lib/vaultFiles";
import { giphyUrl } from "@/lib/ofMedia";
import { stripOFHtml } from "@/lib/ofHtml";

export function scriptDraftFromMessage(msg: OFMessage): SavedReplyDraft {
  // Vault ids only: a saved reply stores numeric OF media ids. Free previews
  // lead, since the composer reads a script's first `previews.length` tiles
  // as the free ones.
  const media = (msg.media ?? [])
    .map((m) => ({ id: Number(m.id), type: m.type, files: vaultFilesFromChat(m.files) }))
    .filter((m) => Number.isSafeInteger(m.id) && m.id > 0);
  const price = msg.price && msg.price > 0 ? msg.price : 0;
  const previewSet = new Set(price > 0 ? msg.previews ?? [] : []);
  const ordered = [...media.filter((m) => previewSet.has(m.id)), ...media.filter((m) => !previewSet.has(m.id))];
  const text = stripOFHtml(msg.text);
  return {
    title: text.split("\n")[0].slice(0, 40) || null,
    text,
    price,
    lockedText: price > 0 && !!msg.lockedText,
    media: ordered,
    previews: ordered.filter((m) => previewSet.has(m.id)).map((m) => m.id),
    gifId: msg.giphyId ?? null,
    gifUrl: msg.giphyId ? giphyUrl(msg.giphyId) : null,
  };
}

/** Whether saving `msg` as a script keeps anything: text, a vault media item
 *  or a GIF. Our bubble's menu offers "Save as script" only then. */
export function scriptDraftHasContent(msg: OFMessage): boolean {
  const d = scriptDraftFromMessage(msg);
  return !!d.text || !!d.media?.length || !!d.gifId;
}

export function scriptPickWarning(
  t: PickedTemplate,
  byMedia: Record<string, FanVaultEntry> | undefined,
): string | null {
  const bought = byMedia ? t.media.filter((m) => byMedia[String(m.id)]?.was_purchased).length : 0;
  const deleted = t.removedMediaIds?.length ?? 0;
  if (!bought && !deleted) return null;
  const lines = ["Use script?"];
  if (bought) {
    lines.push(bought === t.media.length
      ? "This fan already bought the media in this script."
      : `This fan already bought ${bought} of the ${t.media.length} media in this script.`);
  }
  if (deleted) lines.push("One or more of the media files in this script have been deleted from the vault.");
  return lines.join("\n\n");
}
