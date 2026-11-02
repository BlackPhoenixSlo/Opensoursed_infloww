/**
 * PinnedPanel's row text: `stripPreview` drops tags, collapses whitespace and cuts to `max` with "…"; `fmtTime` is
 * the bare clock for a pin from today and "<short date> <clock>" for an older one, "" for no or a bad stamp. The
 * clock is `clockTime` (en-US, lower-case am/pm); the short date is the host locale's, so rows check the stamp's
 * month and day (as the host locale writes them) appear before the clock, not the exact string. "Same date, last
 * year" can't tell the stamp's date from today's by design (no year in the short date).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fmtTime, stripPreview } from "@/components/chat/PinnedPanel";

describe("stripPreview", () => {
  it.each([
    // label,                  html,                                  max, preview
    ["plain",                  "hello",                               120, "hello"],
    ["tags dropped",           "<p>Hi <b>there</b></p>",              120, "Hi there"],
    ["whitespace collapsed",   "  a \n\n\t b  ",                      120, "a b"],
    ["<br> with a space",      "a<br/> b",                            120, "a b"],
    // BUG: see PR — a tag is removed without a space, so lines and paragraphs glue together.
    ["<br> glues words",       "line one<br>line two",                120, "line oneline two"],
    ["<p><p> glues words",     "<p>one</p><p>two</p>",                120, "onetwo"],
    // BUG: see PR — entities stay encoded; the row renders them literally ("Tom &amp; Jerry").
    ["entities kept",          "Tom &amp; Jerry &lt;3 &#39;x&#39;",   120, "Tom &amp; Jerry &lt;3 &#39;x&#39;"],
    ["empty",                  "",                                    120, ""],
    ["only tags",              "<p><br></p>",                         120, ""],
    ["length max - 1",         "abcde",                               6,   "abcde"],
    ["length max",             "abcdef",                              6,   "abcdef"],
    ["length max + 1",         "abcdefg",                             6,   "abcde…"],
    ["cut counts text only",   "<p>abc<b>def</b></p>",                6,   "abcdef"],
    ["cut after strip",        "<p>abc <b>defgh</b></p>",             6,   "abc d…"],
  ] as const)("%s", (_l, html, max, want) => {
    expect(stripPreview(html, max)).toBe(want);
  });
});

describe("fmtTime", () => {
  // Now: Thu 15 Oct 2026 14:00 local.
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 15, 14, 0));
  });
  afterEach(() => vi.useRealTimers());

  it.each([undefined, "", "nope", "2026-13-45T99:00:00Z"])("%j → empty", (iso) => {
    expect(fmtTime(iso)).toBe("");
  });

  it.each([
    // label,                  local stamp,                         clock
    ["today, morning",         new Date(2026, 9, 15, 9, 5),        "9:05 am"],
    ["today, midnight",        new Date(2026, 9, 15, 0, 0),        "12:00 am"],
    ["today, later than now",  new Date(2026, 9, 15, 23, 59),      "11:59 pm"],
  ] as const)("%s → bare clock", (_l, d, want) => {
    expect(fmtTime(d.toISOString())).toBe(want);
  });

  it.each([
    ["yesterday 23:59",        new Date(2026, 9, 14, 23, 59),      "11:59 pm"],
    ["tomorrow 00:00",         new Date(2026, 9, 16, 0, 0),        "12:00 am"],
    ["last week",              new Date(2026, 9, 8, 13, 30),       "1:30 pm"],
    ["same day, last month",   new Date(2026, 8, 15, 14, 0),       "2:00 pm"],
    ["same date, last year",   new Date(2025, 9, 15, 14, 0),       "2:00 pm"],
  ] as const)("%s → short date + clock", (_l, d, clock) => {
    const out = fmtTime(d.toISOString());
    expect(out.endsWith(` ${clock}`)).toBe(true);
    const date = out.slice(0, -clock.length - 1);
    const want = new Intl.DateTimeFormat([], { month: "short", day: "numeric" })
      .formatToParts(d)
      .filter((p) => p.type === "month" || p.type === "day")
      .map((p) => p.value);
    expect(want).toHaveLength(2);
    for (const p of want) expect(date).toContain(p);
  });
});
