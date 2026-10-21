/**
 * The creator clock: a zone's UTC offset right now, as minutes and its label.
 *
 * A pure function over Intl, shared by the top bar, the clock records and the
 * applied-settings view so they cannot disagree on an offset.
 */

/**
 * A zone's offset RIGHT NOW, as minutes AND its display label.
 *
 * ONE Intl round-trip with the label DERIVED from the number, so a caller that
 * groups by offset and a caller that prints one can never disagree. The label is
 * not parsed back into a number anywhere — a display string must not be
 * load-bearing in logic.
 */
export function zoneOffsetNow(tz: string): { minutes: number; label: string } | null {
  try {
    const now = new Date();
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: tz, hour12: false, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).formatToParts(now);
    const at = (t: string) => Number(parts.find((p) => p.type === t)?.value);
    // The same instant read as if the zone's wall clock were UTC; the gap IS the
    // offset. `% 24` because ICU spells midnight "24" in some versions.
    const asUtc = Date.UTC(at("year"), at("month") - 1, at("day"),
                           at("hour") % 24, at("minute"), at("second"));
    // `|| 0` normalises the -0 that Math.round hands back for UTC itself. It is
    // equal to 0 everywhere it matters, but it is the kind of value that shows up
    // in a stored config or a log one day and costs someone an afternoon.
    const minutes = Math.round((asUtc - now.getTime()) / 60_000) || 0;
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
