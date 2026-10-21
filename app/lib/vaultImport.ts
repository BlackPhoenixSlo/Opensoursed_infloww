/**
 * The vault import's upload protocol, as a plain function so the card's
 * `useMutation` only keeps the UI state.
 *
 * The first file opens the run (with the Drive links, the folder and the fan);
 * every other file follows in its own request, so the relay starts uploading
 * the first to OnlyFans while the rest are still on their way.
 */

import { relay, type RelayContext } from "@/lib/relay";

const BATCH = "/api/of/v2/vault/upload/batch";
const APPEND = `${BATCH}/append`;

/** The fan a linked-fan import sends to, as `GET …/vault/upload/fan` resolved
 *  it. The batch route resolves the username again and refuses a different id. */
export interface ResolvedFan {
  id: number;
  username: string;
  name: string | null;
}

export interface VaultBatch {
  /** One file's details for the route's `meta`, or null for none. */
  metaOf: (f: File) => object | null;
  driveLinks?: string;
  folder?: string;
  fan?: ResolvedFan | null;
}

/** Send `files` (and any Drive links) as one run. `onTaken` fires each time the
 *  relay has accepted a request — with the file it took, or null for a
 *  links-only start — and gets the run id from the first. Returns the run id.
 *
 *  An append that fails tells the run nothing else is coming, so it finishes
 *  now instead of waiting out its idle limit, and rethrows: the files it never
 *  took are the caller's still. */
export async function sendVaultBatch(
  files: readonly File[],
  batch: VaultBatch,
  ctx: RelayContext,
  onTaken: (file: File | null, runId: string | undefined) => void,
): Promise<string | undefined> {
  const [first, ...rest] = files;
  const form = new FormData();
  if (first) {
    form.append("files", first, first.name);
    form.append("meta", JSON.stringify([batch.metaOf(first)]));
  }
  if (batch.driveLinks) form.append("drive_links", batch.driveLinks);
  if (batch.folder) form.append("list_id", batch.folder);
  if (batch.fan) {
    form.append("fan_username", batch.fan.username);
    form.append("fan_id", String(batch.fan.id));
  }
  if (rest.length) form.append("keep_open", "1");
  const r = await relay.uploadForm<{ run_id?: string }>(BATCH, form, ctx);
  const runId = r?.run_id;
  onTaken(first ?? null, runId);
  if (!rest.length) return runId;
  if (!runId) throw new Error("The relay started no run for the remaining files");
  for (const [i, f] of rest.entries()) {
    const more = new FormData();
    more.append("run_id", runId);
    more.append("files", f, f.name);
    more.append("meta", JSON.stringify([batch.metaOf(f)]));
    if (i === rest.length - 1) more.append("last", "1");
    try {
      await relay.uploadForm(APPEND, more, ctx);
    } catch (e) {
      const done = new FormData();
      done.append("run_id", runId);
      done.append("last", "1");
      void relay.uploadForm(APPEND, done, ctx).catch(() => {});
      throw e;
    }
    onTaken(f, runId);
  }
  return runId;
}
