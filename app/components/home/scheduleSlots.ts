/**
 * The owner's "Scheduled shifts" rows: the Agency's Shift occurrences coalesced into one row per time slot (same
 * start, end and zone), the employees of every Shift in it listed once. The row's key is the slot itself, so two
 * Shifts at the same time never collide on a key or lose the second one's employees (#8). Times compare as instants, so a slot that crosses midnight or a
 * DST change sorts and coalesces by when it happens, not by its text.
 */
import type { ShiftEmployee, ShiftOccurrence } from "@/lib/shifts";

export interface ScheduleSlot {
  /** Unique per row: the slot's start and end instants and its zone. */
  key: string;
  occurrence_start: string;
  occurrence_end: string;
  tz: string;
  employees: ShiftEmployee[];
}

const addOnce = <T extends { id: unknown }>(into: T[], items: readonly T[]) => {
  for (const item of items) if (!into.some((x) => x.id === item.id)) into.push(item);
};

export function groupOccurrences(occurrences: readonly ShiftOccurrence[]): ScheduleSlot[] {
  const slots = new Map<string, ScheduleSlot>();
  for (const o of occurrences) {
    const key = `${Date.parse(o.occurrence_start)}:${Date.parse(o.occurrence_end)}:${o.tz}`;
    let slot = slots.get(key);
    if (!slot) {
      slot = { key, occurrence_start: o.occurrence_start, occurrence_end: o.occurrence_end, tz: o.tz, employees: [] };
      slots.set(key, slot);
    }
    addOnce(slot.employees, o.employees);
  }
  return [...slots.values()].sort((a, b) =>
    Date.parse(a.occurrence_start) - Date.parse(b.occurrence_start)
    || Date.parse(a.occurrence_end) - Date.parse(b.occurrence_end)
    || a.key.localeCompare(b.key));
}
