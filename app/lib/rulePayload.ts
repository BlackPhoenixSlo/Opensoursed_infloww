import { parseJsonObject, type RawJsonCodec } from "@/lib/rawJsonReducer";

export type Payload = Record<string, unknown>;

// dry_run belongs to the Dry-run switch; a typed one is refused, not dropped, or a live rule would save as dry.
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
