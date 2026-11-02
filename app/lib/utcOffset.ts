/** "UTC+02:00" for an offset in minutes east of UTC. */
export function utcOffsetFromMinutes(mins: number): string {
  const sign = mins < 0 ? "-" : "+";
  const abs = Math.abs(mins);
  const hh = String(Math.floor(abs / 60)).padStart(2, "0");
  const mm = String(abs % 60).padStart(2, "0");
  return `UTC${sign}${hh}:${mm}`;
}

/** "UTC-10:00": the zone's offset now, as the bundle prints a `reportTimezoneId`
 *  (capture #16); the browser's zone when `timeZone` is null. The Dashboard header,
 *  Tracking links' title and `InflowwPageHeader`'s `utc` read it. */
export function utcOffsetLabel(timeZone: string | null): string {
  const name = new Intl.DateTimeFormat("en-US", { timeZone: timeZone ?? undefined, timeZoneName: "longOffset" })
    .formatToParts(new Date())
    .find((p) => p.type === "timeZoneName")?.value ?? "GMT";
  if (name === "GMT") return utcOffsetFromMinutes(0);
  const m = /^GMT([+-])(\d\d):(\d\d)$/.exec(name);
  if (!m) return `UTC${name.replace(/^GMT/, "")}`; // an odd shape Intl may print: as is, as before
  return utcOffsetFromMinutes((m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3])));
}
