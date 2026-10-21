/** "UTC-10:00": the zone's offset now, as the bundle prints a `reportTimezoneId`
 *  (capture #16); the browser's zone when `timeZone` is null. The Dashboard header,
 *  Tracking links' title and `InflowwPageHeader`'s `utc` read it. */
export function utcOffsetLabel(timeZone: string | null): string {
  const name = new Intl.DateTimeFormat("en-US", { timeZone: timeZone ?? undefined, timeZoneName: "longOffset" })
    .formatToParts(new Date())
    .find((p) => p.type === "timeZoneName")?.value ?? "GMT";
  const offset = name.replace(/^GMT/, "");
  return `UTC${offset || "+00:00"}`;
}
