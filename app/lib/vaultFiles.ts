import type { VaultFiles } from "@/lib/relay";

type MaybeUrl = { url?: string | null } | null | undefined;

/** A chat message's media files as vault files, for attaching a sent media
 *  item again (a chat-media resend, a script saved from a bubble). A vault
 *  file's url is a string, so a variant without one is dropped; send-by-id
 *  does not need it, the chip shows a placeholder until OF signs it again. */
export function vaultFilesFromChat(
  files: { thumb?: MaybeUrl; preview?: MaybeUrl; squarePreview?: MaybeUrl; full?: MaybeUrl } | null | undefined,
): VaultFiles | null {
  if (!files) return null;
  const one = (f: MaybeUrl) => (f && f.url ? { url: f.url } : undefined);
  return { thumb: one(files.thumb), preview: one(files.preview),
           squarePreview: one(files.squarePreview), full: one(files.full) };
}
