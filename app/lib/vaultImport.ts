import { relay, type RelayContext } from "@/lib/relay";

const BATCH = "/api/of/v2/vault/upload/batch";
const APPEND = `${BATCH}/append`;

export interface ResolvedFan {
  id: number;
  username: string;
  name: string | null;
}

export interface VaultBatch {
  metaOf: (f: File) => object | null;
  driveLinks?: string;
  folder?: string;
  fan?: ResolvedFan | null;
}

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
