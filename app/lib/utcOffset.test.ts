/**
 * lib/utcOffset — `utcOffsetFromMinutes` (TopBar's copy, moved) and `utcOffsetLabel`, now built on it. The zone rows
 * prove the label prints what the Intl-string version did.
 */
import { describe, expect, it } from "vitest";

import { utcOffsetFromMinutes, utcOffsetLabel } from "@/lib/utcOffset";

/** `utcOffsetLabel` before it parsed into minutes, verbatim. */
function legacyUtcOffsetLabel(timeZone: string | null): string {
  const name = new Intl.DateTimeFormat("en-US", { timeZone: timeZone ?? undefined, timeZoneName: "longOffset" })
    .formatToParts(new Date())
    .find((p) => p.type === "timeZoneName")?.value ?? "GMT";
  const offset = name.replace(/^GMT/, "");
  return `UTC${offset || "+00:00"}`;
}

describe("utcOffsetFromMinutes", () => {
  it.each([
    [0, "UTC+00:00"], [60, "UTC+01:00"], [-330, "UTC-05:30"], [345, "UTC+05:45"], [-720, "UTC-12:00"],
  ])("%i → %s", (mins, want) => {
    expect(utcOffsetFromMinutes(mins)).toBe(want);
  });
});

describe("utcOffsetLabel", () => {
  it.each([
    ["UTC", "UTC+00:00"], ["Asia/Kolkata", "UTC+05:30"], ["Asia/Kathmandu", "UTC+05:45"],
    ["Etc/GMT+12", "UTC-12:00"], ["Asia/Tokyo", "UTC+09:00"],
  ])("%s → %s", (tz, want) => {
    expect(utcOffsetLabel(tz)).toBe(want);
  });

  it.each(["UTC", "Asia/Kolkata", "Asia/Kathmandu", "Etc/GMT+12", "Asia/Tokyo", "America/St_Johns", null])(
    "%s prints what the old Intl-string version did",
    (tz) => {
      expect(utcOffsetLabel(tz)).toBe(legacyUtcOffsetLabel(tz));
    },
  );
});
