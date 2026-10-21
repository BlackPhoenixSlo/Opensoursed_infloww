import { describe, expect, it, vi } from "vitest";
import { closeDatepicker, daysSelected, monthWeeks, openDatepicker, parseDay, pick, pickerMonths, tabDate, type Day } from "./ofMirrorDatepicker";

const D = (s: string) => parseDay(s)!;
const TODAY = D("2026-10-17");
const START = D("2021-09-28");

describe("OF's Custom date picker: its rules (PeriodDatePicker)", () => {
  it("the title counts both ends; the tabs read 'MMM D, YYYY'", () => {
    expect(daysSelected(D("2025-02-02"), D("2026-10-12"))).toBe("618 days selected"); // the captured picker
    expect(daysSelected(D("2026-10-17"), D("2026-10-17"))).toBe("1 day selected");
    expect(tabDate(D("2025-02-02"))).toBe("Feb 2, 2025");
    expect(parseDay("2026-02-30")).toBeNull();
  });

  it("a day on the start tab sets the start and moves to the end tab; an end before the start swaps them", () => {
    const s = { start: D("2026-09-17"), end: D("2026-10-17"), fromTab: true, today: TODAY, min: START };
    expect(pick(s, D("2026-10-01"))).toEqual({ start: D("2026-10-01"), end: D("2026-10-17"), fromTab: false });
    expect(pick({ ...s, fromTab: false }, D("2026-10-05"))).toEqual({ start: D("2026-09-17"), end: D("2026-10-05"), fromTab: false });
    expect(pick({ ...s, fromTab: false }, D("2026-09-01"))).toEqual({ start: D("2026-09-01"), end: D("2026-09-17"), fromTab: true });
    expect(pick(s, D("2026-10-18"))).toBeNull(); // after today
    expect(pick(s, D("2021-09-27"))).toBeNull(); // before the Creator's start
  });

  it("the grid: Sunday-first weeks from the 1st's week to the last day's (the captured February 2025: Jan 26 to Mar 1)", () => {
    const weeks = monthWeeks(D("2025-02-01"));
    expect(weeks).toHaveLength(5);
    expect(weeks[0][0]).toEqual(D("2025-01-26"));
    expect(weeks.at(-1)!.at(-1)).toEqual(D("2025-03-01"));
  });

  it("the month menu: this month back to the Creator's start", () => {
    const months = pickerMonths(TODAY, D("2026-08-03"));
    expect(months.map((m) => `${m.y}-${m.m}`)).toEqual(["2026-10", "2026-9", "2026-8"]);
  });
});

describe("OF's Custom date picker in a page", () => {
  const open = (onApply = vi.fn<(a: Day, b: Day) => void>()) => {
    document.body.innerHTML = "";
    openDatepicker(document, { start: D("2026-09-17"), end: D("2026-10-17"), today: TODAY, userStart: START, onApply });
    return onApply;
  };
  const text = (sel: string) => document.querySelector(sel)!.textContent!.trim();
  const click = (sel: string) => (document.querySelector(sel) as HTMLElement).click();

  it("OF's markup: the overlay's popup, title, tabs, month, grid with today and the range, Cancel and Apply", () => {
    open();
    expect(document.querySelector("[data-oi-picker]")!.className).toBe("vdatetime custom-datepicker");
    expect(document.querySelector(".custom-datepicker > div:not([class]) > .vdatetime-overlay + .vdatetime-popup")).not.toBeNull();
    expect(text(".vdatetime-popup__title")).toBe("31 days selected");
    expect([...document.querySelectorAll(".vdatetime-popup__tab")].map((t) => t.textContent!.trim())).toEqual(["Sep 17, 2026", "Oct 17, 2026"]);
    expect(text(".b-streaks-swither__time")).toBe("September 2026");
    expect(text("[data-oi-day='2026-09-17'] .v-calendar-weekly__day-label span")).toBe("17");
    expect(document.querySelector("[data-oi-day='2026-09-17'] .v-calendar-weekly__day-label span")!.className).toBe("active start-range");
    expect(document.querySelector("[data-oi-day='2026-09-17'] .v-event.range")!.className).toBe("v-event v-event-start range white--text");
    expect(document.querySelector("[data-oi-day='2026-09-20'] .v-event.range")!.getAttribute("style")).toContain("width: 695%");
    expect([...document.querySelectorAll(".vdatetime-popup__actions button")].map((b) => b.textContent!.trim())).toEqual(["Cancel", "Apply"]);
  });

  it("picking: a start, the next month, an end, then Apply hands the days back and closes", () => {
    const onApply = open();
    click("[data-oi-day='2026-09-03']");
    expect(text(".vdatetime-popup__title")).toBe("45 days selected");
    expect(document.querySelector(".vdatetime-popup__tab.time")!.classList.contains("active")).toBe(true);
    expect(text(".b-streaks-swither__time")).toBe("October 2026"); // the end tab shows the end's month
    expect((document.querySelector("[data-oi-month='next']") as HTMLButtonElement).disabled).toBe(true); // this month
    click("[data-oi-month='prev']");
    expect(text(".b-streaks-swither__time")).toBe("September 2026");
    click("[data-oi-day='2026-09-15']");
    expect(text(".vdatetime-popup__title")).toBe("13 days selected");
    click("[data-oi-picker-apply]");
    expect(onApply).toHaveBeenCalledWith(D("2026-09-03"), D("2026-09-15"));
    expect(document.querySelector("[data-oi-picker]")).toBeNull();
  });

  it("the month menu jumps to a month; Cancel, Escape and the overlay close without applying", () => {
    const onApply = open();
    click("[data-oi-months]");
    expect(document.querySelector("[data-oi-picker-months] .m-active")!.textContent!.trim()).toBe("September 2026");
    click("[data-oi-month-pick='2026-01-01']");
    expect(text(".b-streaks-swither__time")).toBe("January 2026");
    expect(document.querySelector("[data-oi-picker-months]")).toBeNull();
    click("[data-oi-picker-close].vdatetime-overlay");
    expect(document.querySelector("[data-oi-picker]")).toBeNull();
    open(onApply);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(document.querySelector("[data-oi-picker]")).toBeNull();
    open(onApply);
    click(".custom-datepicker-button-cancel");
    expect(document.querySelector("[data-oi-picker]")).toBeNull();
    expect(onApply).not.toHaveBeenCalled();
    closeDatepicker(document);
  });

  it("a page without the grid's styles (only Statistics links 45647.css) gets them once, next to its app.css", () => {
    const head = document.head.innerHTML;
    document.head.innerHTML = '<link rel="stylesheet" href="/of-mirror/static/b1/app.css">';
    open();
    open();
    expect([...document.querySelectorAll("link[rel='stylesheet']")].map((l) => l.getAttribute("href"))).toEqual(["/of-mirror/static/b1/app.css", "/of-mirror/static/b1/45647.css"]);
    closeDatepicker(document);
    document.head.innerHTML = head;
  });
});
