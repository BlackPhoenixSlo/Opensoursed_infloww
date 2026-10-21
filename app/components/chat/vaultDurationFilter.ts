/**
 * The Vault picker's length filter, shown when a Fan is in scope
 * (docs/spec/phase-04-composer-ppv-vault.md, Vault picker, story 52). It
 * narrows the items already loaded, on the client: the relay has no duration
 * parameter. Choosing a range hides everything that is not a video.
 */
import { type VaultMedia } from "@/lib/relay";

export const DURATION_RANGES = [
  { value: "any", label: "Any length" },
  { value: "under-1", label: "Under 1 min" },
  { value: "1-5", label: "1–5 min" },
  { value: "over-5", label: "Over 5 min" },
] as const;

export type DurationRange = (typeof DURATION_RANGES)[number]["value"];

/** Whether `m` passes the range. "1–5 min" includes both ends (60 s and
 *  300 s); a video with no known duration passes only "Any length". */
export function inDurationRange(m: VaultMedia, range: DurationRange): boolean {
  if (range === "any") return true;
  if (m.type !== "video" || m.duration == null) return false;
  if (range === "under-1") return m.duration < 60;
  if (range === "1-5") return m.duration >= 60 && m.duration <= 300;
  return m.duration > 300;
}
