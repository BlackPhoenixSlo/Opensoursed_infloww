import type { VaultMedia } from "@/lib/relay";

import type { PickedGif } from "./GifPicker";

// OF accepts one GIF per send: the first rides the message, the rest follow as GIF-only sends.
export function gifPlan(pickedGifs: readonly PickedGif[]): { first: PickedGif | undefined; trailing: PickedGif[] } {
  return { first: pickedGifs[0], trailing: pickedGifs.slice(1) };
}

export function scheduledToast(scheduledAt: string, now: number, maxMinutes: number): string {
  const fireAt = new Date(scheduledAt).getTime();
  const minsFromNow = Math.max(1, Math.round((fireAt - now) / 60_000));
  return fireAt - now <= maxMinutes * 60_000
    ? `⏱ Scheduled · sending in ${minsFromNow} min (saved — survives reload)`
    : `⏱ Queued on OF for ${new Date(scheduledAt).toLocaleString()}`;
}

export function previewsToRevoke(
  prev: readonly VaultMedia[], live: readonly VaultMedia[], sent: ReadonlySet<string>,
): string[] {
  const shown = new Set(live.map((m) => m._localPreview));
  return prev.map((m) => m._localPreview).filter((u): u is string => !!u && !shown.has(u) && !sent.has(u));
}
