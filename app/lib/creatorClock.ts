/**
 * The creator clock: a zone's UTC offset at an instant (or now), as minutes and its label.
 *
 * A pure function over Intl, shared by the top bar, the clock records and the
 * applied-settings view so they cannot disagree on an offset.
 */

/** A zone's offset RIGHT NOW: `zoneOffsetAt` at this instant. */
export function zoneOffsetNow(tz: string): { minutes: number; label: string } | null {
  return zoneOffsetAt(tz, Date.now());
}

/**
 * A zone's offset at `at`, as minutes AND its display label.
 *
 * ONE Intl round-trip with the label DERIVED from the number, so a caller that
 * groups by offset and a caller that prints one can never disagree. The label is
 * not parsed back into a number anywhere — a display string must not be
 * load-bearing in logic.
 */
export function zoneOffsetAt(tz: string, at: Date | number): { minutes: number; label: string } | null {
  try {
    const instant = new Date(at);
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: tz, hour12: false, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).formatToParts(instant);
    const part = (t: string) => Number(parts.find((p) => p.type === t)?.value);
    // The same instant read as if the zone's wall clock were UTC; the gap IS the
    // offset. `% 24` because ICU spells midnight "24" in some versions.
    const asUtc = Date.UTC(part("year"), part("month") - 1, part("day"),
                           part("hour") % 24, part("minute"), part("second"));
    // `|| 0` normalises the -0 that Math.round hands back for UTC itself. It is
    // equal to 0 everywhere it matters, but it is the kind of value that shows up
    // in a stored config or a log one day and costs someone an afternoon.
    const minutes = Math.round((asUtc - instant.getTime()) / 60_000) || 0;
    if (!Number.isFinite(minutes)) return null;
    const sign = minutes < 0 ? "-" : "+";
    const abs = Math.abs(minutes);
    const rest = abs % 60;
    return {
      minutes,
      label: `UTC${sign}${Math.floor(abs / 60)}${rest ? `:${String(rest).padStart(2, "0")}` : ""}`,
    };
  } catch {
    return null;
  }
}

/**
 * The zone as "America/New_York (UTC-4)" for a range's stamps: the start's offset, both as
 * "(UTC-4 → UTC-5)" when the start's and end's offsets differ, the bare zone for a zone Intl does not
 * know. Both ends are inclusive: `toMs` is the range's last instant.
 */
export function rangeOffsetLabel(tz: string, fromMs: number, toMs: number): string {
  const from = zoneOffsetAt(tz, fromMs);
  const to = zoneOffsetAt(tz, toMs);
  if (!from || !to) return tz;
  return `${tz} (${from.minutes === to.minutes ? from.label : `${from.label} → ${to.label}`})`;
}
