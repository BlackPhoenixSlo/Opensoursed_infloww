/**
 * Raw-JSON codec over a ready-made rule payload (automations/ReadyMadePanel):
 * a JSON object (blank text = `{}`). `dry_run` is the Dry-run switch's (it re-merges it on save), so a typed
 * `dry_run` is refused rather than dropped: silently stripping it would save a rule live that the text says is dry.
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
  parse: (text) => {
    const p = parseJsonObject(text, "Payload", '{ "posts": [ … ] } or { "messages": [ … ] }');
    if ("dry_run" in p) throw new Error('Remove "dry_run" here: the Dry run switch sets it.');
    return p;
  },
};
