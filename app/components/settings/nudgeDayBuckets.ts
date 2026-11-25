import { type NudgeSlotEntry, type NudgeSlots } from "@/hooks/useNudgeConfig";

// Mirrors the relay's _pick_pool (service/automations/nudge_online.py): per field, the most specific bucket that has it wins.
export type DayBucket =
  | "default" | "weekday" | "weekend"
  | "monday" | "tuesday" | "wednesday" | "thursday" | "friday" | "saturday" | "sunday";

export const DAY_BUCKETS: { key: DayBucket; label: string }[] = [
  { key: "default", label: "Every day" },
  { key: "weekday", label: "Weekdays" },
  { key: "weekend", label: "Weekend" },
  { key: "monday", label: "Mon" },
  { key: "tuesday", label: "Tue" },
  { key: "wednesday", label: "Wed" },
  { key: "thursday", label: "Thu" },
  { key: "friday", label: "Fri" },
  { key: "saturday", label: "Sat" },
  { key: "sunday", label: "Sun" },
];

const LONG: Record<DayBucket, string> = {
  default: "Every day", weekday: "Weekdays", weekend: "Weekend",
  monday: "Mondays", tuesday: "Tuesdays", wednesday: "Wednesdays", thursday: "Thursdays",
  friday: "Fridays", saturday: "Saturdays", sunday: "Sundays",
};
export const bucketLabel = (b: DayBucket): string => LONG[b];

export function fallbackChain(bucket: DayBucket): DayBucket[] {
  if (bucket === "default") return [];
  if (bucket === "weekday" || bucket === "weekend") return ["default"];
  return [bucket === "saturday" || bucket === "sunday" ? "weekend" : "weekday", "default"];
}

export interface Inherited {
  text: { from: DayBucket; lines: string[] } | null;
  image: { from: DayBucket; ids: number[] } | null;
}

export function inherited(slots: NudgeSlots, bucket: DayBucket, slotKey: string): Inherited {
  let text: Inherited["text"] = null;
  let image: Inherited["image"] = null;
  for (const b of fallbackChain(bucket)) {
    const e = slots[b]?.[slotKey];
    if (!text && e?.text?.length) text = { from: b, lines: e.text };
    if (!image && e?.image?.length) image = { from: b, ids: e.image };
  }
  return { text, image };
}

const isEmpty = (e: NudgeSlotEntry | undefined): boolean => !e || (!e.text?.length && !e.image?.length);

export function bucketHasContent(slots: NudgeSlots, bucket: DayBucket): boolean {
  return Object.values(slots[bucket] ?? {}).some((e) => !isEmpty(e));
}

export function setSlot(slots: NudgeSlots, bucket: DayBucket, slotKey: string, entry: NudgeSlotEntry): NudgeSlots {
  const day = { ...(slots[bucket] ?? {}) };
  if (isEmpty(entry)) delete day[slotKey];
  else day[slotKey] = entry;
  const next = { ...slots };
  if (bucket !== "default" && Object.keys(day).length === 0) delete next[bucket];
  else next[bucket] = day;
  return next;
}

export function shownImageIds(slots: NudgeSlots, bucket: DayBucket, slotKeys: string[]): number[] {
  const ids = new Set<number>();
  for (const k of slotKeys) {
    const own = slots[bucket]?.[k]?.image ?? [];
    for (const id of own.length ? own : inherited(slots, bucket, k).image?.ids ?? []) ids.add(id);
  }
  return [...ids];
}
