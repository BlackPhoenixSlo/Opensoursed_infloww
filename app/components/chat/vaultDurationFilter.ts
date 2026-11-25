import { type VaultMedia } from "@/lib/relay";

export const DURATION_RANGES = [
  { value: "any", label: "Any length" },
  { value: "under-1", label: "Under 1 min" },
  { value: "1-5", label: "1–5 min" },
  { value: "over-5", label: "Over 5 min" },
] as const;

export type DurationRange = (typeof DURATION_RANGES)[number]["value"];

export function inDurationRange(m: VaultMedia, range: DurationRange): boolean {
  if (range === "any") return true;
  if (m.type !== "video" || m.duration == null) return false;
  if (range === "under-1") return m.duration < 60;
  if (range === "1-5") return m.duration >= 60 && m.duration <= 300;
  return m.duration > 300;
}
