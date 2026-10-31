/**
 * Raw-JSON codec over a ready-made rule payload (automations/ReadyMadePanel):
 * a JSON object (blank text = `{}`) with `dry_run` stripped — the Dry-run
 * switch owns it and re-merges it on save.
 */

import { parseJsonObject, type RawJsonCodec } from "@/lib/rawJsonReducer";

export type Payload = Record<string, unknown>;

/** `p` without `dry_run` (a copy). */
export function withoutDryRun(p: Payload | undefined): Payload {
  const out = { ...p };
  delete out.dry_run;
  return out;
}

export const PAYLOAD_RAW: RawJsonCodec<Payload> = {
  format: (p) => JSON.stringify(p, null, 2),
  parse: (text) =>
    withoutDryRun(parseJsonObject(text, "Payload", '{ "posts": [ … ] } or { "messages": [ … ] }')),
};
