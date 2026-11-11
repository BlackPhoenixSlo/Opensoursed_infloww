/**
 * Nudge online's day buckets — which day the "Message lines" editor edits, and what a day's empty part falls back
 * to. Mirrors the relay's `_pick_pool` (service/automations/nudge_online.py): per FIELD, the lines come from the most
 * specific bucket that has lines and the images from the most specific that has images — day → weekday/weekend →
 * every day. Pure; NudgeSlotPools only renders it.
 */

import { type NudgeSlotEntry, type NudgeSlots } from "@/hooks/useNudgeConfig";

export type DayBucket =
  | "default" | "weekday" | "weekend"
  | "monday" | "tuesday" | "wednesday" | "thursday" | "friday" | "saturday" | "sunday";

/** The picker's chips, in order, with their labels. */
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

/** Long names, for sentences ("Only on Fridays"). */
const LONG: Record<DayBucket, string> = {
  default: "Every day", weekday: "Weekdays", weekend: "Weekend",
  monday: "Mondays", tuesday: "Tuesdays", wednesday: "Wednesdays", thursday: "Thursdays",
  friday: "Fridays", saturday: "Saturdays", sunday: "Sundays",
};
export const bucketLabel = (b: DayBucket): string => LONG[b];

/** The buckets a part of `bucket` falls back to, nearest first. */
export function fallbackChain(bucket: DayBucket): DayBucket[] {
  if (bucket === "default") return [];
  if (bucket === "weekday" || bucket === "weekend") return ["default"];
  return [bucket === "saturday" || bucket === "sunday" ? "weekend" : "weekday", "default"];
}

/** What an empty field of `bucket`'s slot `slotKey` uses instead: the nearest fallback bucket that has it. */
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

/** Whether `bucket` has anything of its own (the chip's dot). */
export function bucketHasContent(slots: NudgeSlots, bucket: DayBucket): boolean {
  return Object.values(slots[bucket] ?? {}).some((e) => !isEmpty(e));
}

/** `slots` with `bucket`'s slot `slotKey` set to `entry`. An entry left with no lines and no images is dropped, and
 *  a day bucket left with no slots too, so a cleared day falls back cleanly and the JSON stays tidy. The every-day
 *  bucket is always kept. */
export function setSlot(slots: NudgeSlots, bucket: DayBucket, slotKey: string, entry: NudgeSlotEntry): NudgeSlots {
  const day = { ...(slots[bucket] ?? {}) };
  if (isEmpty(entry)) delete day[slotKey];
  else day[slotKey] = entry;
  const next = { ...slots };
  if (bucket !== "default" && Object.keys(day).length === 0) delete next[bucket];
  else next[bucket] = day;
  return next;
}

/** Every image id the editor shows for `bucket` (a slot's own, else the ones it inherits), for thumbnail lookups. */
export function shownImageIds(slots: NudgeSlots, bucket: DayBucket, slotKeys: string[]): number[] {
  const ids = new Set<number>();
  for (const k of slotKeys) {
    const own = slots[bucket]?.[k]?.image ?? [];
    for (const id of own.length ? own : inherited(slots, bucket, k).image?.ids ?? []) ids.add(id);
  }
  return [...ids];
}
