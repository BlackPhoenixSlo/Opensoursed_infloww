import type { VaultFiles } from "@/lib/relay";

type MaybeUrl = { url?: string | null } | null | undefined;

export function vaultFilesFromChat(
  files: { thumb?: MaybeUrl; preview?: MaybeUrl; squarePreview?: MaybeUrl; full?: MaybeUrl } | null | undefined,
): VaultFiles | null {
  if (!files) return null;
  const one = (f: MaybeUrl) => (f && f.url ? { url: f.url } : undefined);
  return { thumb: one(files.thumb), preview: one(files.preview),
           squarePreview: one(files.squarePreview), full: one(files.full) };
}
