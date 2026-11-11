import { describe, expect, it } from "vitest";
import type { ShiftOccurrence } from "@/lib/shifts";
import { groupOccurrences } from "./scheduleSlots";

const occ = (shift_id: number, start: string, end: string, employees: number[], tz = "UTC"): ShiftOccurrence => ({
  shift_id, occurrence_start: start, occurrence_end: end, start_utc: start, end_utc: end, tz,
  repeat_days: null, repeat_until: null,
  employees: employees.map((id) => ({ id, display_name: `emp${id}` })),
  accounts: [],
});

const view = (o: ShiftOccurrence[]) => groupOccurrences(o).map((s) => ({
  start: s.occurrence_start, emps: s.employees.map((e) => e.id),
}));

describe("groupOccurrences", () => {
  const cases: { name: string; in: ShiftOccurrence[]; out: ReturnType<typeof view> }[] = [
    {
      name: "two Shifts in one slot: one row, every employee once",
      in: [occ(1, "2026-10-14T15:00:00Z", "2026-10-14T19:00:00Z", [7]),
        occ(2, "2026-10-14T15:00:00Z", "2026-10-14T19:00:00Z", [7, 8])],
      out: [{ start: "2026-10-14T15:00:00Z", emps: [7, 8] }],
    },
    {
      name: "a Shift crossing midnight (22:00 to 06:00) is one row, sorted by its start",
      in: [occ(3, "2026-10-15T09:00:00Z", "2026-10-15T12:00:00Z", [1]),
        occ(4, "2026-10-14T22:00:00Z", "2026-10-15T06:00:00Z", [2])],
      out: [
        { start: "2026-10-14T22:00:00Z", emps: [2] },
        { start: "2026-10-15T09:00:00Z", emps: [1] },
      ],
    },
    {
      name: "same start, different end: two rows",
      in: [occ(5, "2026-10-14T22:00:00Z", "2026-10-15T06:00:00Z", [1]),
        occ(6, "2026-10-14T22:00:00Z", "2026-10-15T02:00:00Z", [2])],
      out: [
        { start: "2026-10-14T22:00:00Z", emps: [2] },
        { start: "2026-10-14T22:00:00Z", emps: [1] },
      ],
    },
    {
      // US DST ends Sun 1 Nov 2026 02:00 EDT: 22:00 EDT to 06:00 EST is 9 hours; offsets in the text differ.
      name: "across a DST change, slots compare and sort as instants, not as text",
      in: [occ(7, "2026-10-31T22:00:00-04:00", "2026-11-01T06:00:00-05:00", [1], "America/New_York"),
        occ(8, "2026-11-01T02:00:00Z", "2026-11-01T11:00:00Z", [2], "America/New_York"),
        occ(9, "2026-11-01T01:30:00Z", "2026-11-01T03:00:00Z", [3], "UTC")],
      out: [
        { start: "2026-11-01T01:30:00Z", emps: [3] },
        { start: "2026-10-31T22:00:00-04:00", emps: [1, 2] },
      ],
    },
    {
      name: "same instants in another zone stay a row of their own",
      in: [occ(10, "2026-10-14T15:00:00Z", "2026-10-14T19:00:00Z", [1], "UTC"),
        occ(11, "2026-10-14T15:00:00Z", "2026-10-14T19:00:00Z", [2], "Europe/Berlin")],
      out: [
        { start: "2026-10-14T15:00:00Z", emps: [2] },
        { start: "2026-10-14T15:00:00Z", emps: [1] },
      ],
    },
    { name: "no occurrences, no rows", in: [], out: [] },
  ];
  it.each(cases)("$name", ({ in: input, out }) => {
    expect(view(input)).toEqual(out);
  });

  it("gives every row a unique key, even for two Shifts at the same time", () => {
    const slots = groupOccurrences([
      occ(1, "2026-10-14T15:00:00Z", "2026-10-14T19:00:00Z", [1]),
      occ(2, "2026-10-14T15:00:00Z", "2026-10-14T19:00:00Z", [2]),
      occ(1, "2026-10-21T15:00:00Z", "2026-10-21T19:00:00Z", [1]),
    ]);
    expect(new Set(slots.map((s) => s.key)).size).toBe(slots.length);
    expect(slots).toHaveLength(2);
  });
});
