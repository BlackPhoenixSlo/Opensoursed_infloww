export function utcOffsetFromMinutes(mins: number): string {
  const sign = mins < 0 ? "-" : "+";
  const abs = Math.abs(mins);
  const hh = String(Math.floor(abs / 60)).padStart(2, "0");
  const mm = String(abs % 60).padStart(2, "0");
  return `UTC${sign}${hh}:${mm}`;
}

export function utcOffsetLabel(timeZone: string | null): string {
  const name = new Intl.DateTimeFormat("en-US", { timeZone: timeZone ?? undefined, timeZoneName: "longOffset" })
    .formatToParts(new Date())
    .find((p) => p.type === "timeZoneName")?.value ?? "GMT";
  if (name === "GMT") return utcOffsetFromMinutes(0);
  const m = /^GMT([+-])(\d\d):(\d\d)$/.exec(name);
  if (!m) return `UTC${name.replace(/^GMT/, "")}`;
  return utcOffsetFromMinutes((m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3])));
}
