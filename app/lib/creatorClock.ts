export function zoneOffsetNow(tz: string): { minutes: number; label: string } | null {
  return zoneOffsetAt(tz, Date.now());
}

export function zoneOffsetAt(tz: string, at: Date | number): { minutes: number; label: string } | null {
  try {
    const instant = new Date(at);
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: tz, hour12: false, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).formatToParts(instant);
    const part = (t: string) => Number(parts.find((p) => p.type === t)?.value);
    const asUtc = Date.UTC(part("year"), part("month") - 1, part("day"),
                           // % 24: ICU spells midnight "24" in some versions.
                           part("hour") % 24, part("minute"), part("second"));
    // || 0 normalises the -0 Math.round returns for UTC.
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

export function rangeOffsetLabel(tz: string, fromMs: number, toMs: number): string {
  const from = zoneOffsetAt(tz, fromMs);
  const to = zoneOffsetAt(tz, toMs);
  if (!from || !to) return tz;
  return `${tz} (${from.minutes === to.minutes ? from.label : `${from.label} → ${to.label}`})`;
}
