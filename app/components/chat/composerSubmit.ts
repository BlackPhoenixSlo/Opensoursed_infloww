/**
 * composerSubmit — the pure decisions of the chat Composer's send
 * (`Composer.submit`) and of its blob previews' lifecycle (`useBlobPreviews`).
 * The Composer only calls them.
 *
 *   • `gifPlan`: OF accepts ONE GIF per send (verified live 2026-05-23): the
 *     first rides on the message (`buildSendArgs` sets its `giphyId`), the rest
 *     go after it as GIF-only sends, in pick order.
 *   • `scheduledToast`: the notice once a schedule is enqueued.
 *   • `previewsToRevoke`: blob previews a change of the attached media drops.
 */

import type { VaultMedia } from "@/lib/relay";

import type { PickedGif } from "./GifPicker";

/** The GIF riding on the send, and those sent after it on their own. */
export function gifPlan(pickedGifs: readonly PickedGif[]): { first: PickedGif | undefined; trailing: PickedGif[] } {
  return { first: pickedGifs[0], trailing: pickedGifs.slice(1) };
}

/** The toast once a schedule at `scheduledAt` (ISO) is enqueued at `now`: the
 *  relay's executor sends one within `maxMinutes`, OF queues a later one. */
export function scheduledToast(scheduledAt: string, now: number, maxMinutes: number): string {
  const fireAt = new Date(scheduledAt).getTime();
  const minsFromNow = Math.max(1, Math.round((fireAt - now) / 60_000));
  return fireAt - now <= maxMinutes * 60_000
    ? `⏱ Scheduled · sending in ${minsFromNow} min (saved — survives reload)`
    : `⏱ Queued on OF for ${new Date(scheduledAt).toLocaleString()}`;
}

/** The blob previews the tiles `prev` showed that `live` no longer does, but
 *  those a send took (`sent`: the optimistic bubble shows them until the
 *  server copy arrives). */
export function previewsToRevoke(
  prev: readonly VaultMedia[], live: readonly VaultMedia[], sent: ReadonlySet<string>,
): string[] {
  const shown = new Set(live.map((m) => m._localPreview));
  return prev.map((m) => m._localPreview).filter((u): u is string => !!u && !shown.has(u) && !sent.has(u));
}
