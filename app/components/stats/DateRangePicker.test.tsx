/**
 * DateRangePicker, the reports' range box (page-parity ticket 25): the trigger shows both days (and the hours with
 * `hours`), the popover's presets call back with `presetRange`, a typed date is Custom, and a span of more than a
 * year is refused with Infloww's line. The clock is pinned to Wed 14 Oct 2026 12:00Z, browser zone UTC.
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import DateRangePicker, { REVERSED, SPAN_LIMIT } from "@/components/stats/DateRangePicker";
import { dateBounds, presetRange } from "@/lib/dateRange";

beforeAll(() => vi.stubEnv("TZ", "UTC"));
afterAll(() => vi.unstubAllEnvs());
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-14T12:00:00Z"));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const trigger = () => screen.getByRole("button", { name: /^Date range/ });
const open = () => {
  fireEvent.click(trigger());
  return screen.getByRole("dialog", { name: "Date range" });
};

describe("DateRangePicker", () => {
  it("shows both days in the box, and the hours with `hours`", () => {
    const { rerender } = render(
      <DateRangePicker from="2026-10-07" to="2026-10-14" preset="7d" onChange={() => {}} />,
    );
    expect(trigger()).toHaveTextContent("Oct 7, 2026");
    expect(trigger()).toHaveTextContent("Oct 14, 2026");
    expect(trigger()).not.toHaveTextContent("AM");

    rerender(<DateRangePicker from="2026-10-07T15:00" to="2026-10-14" preset="custom" onChange={() => {}} hours />);
    expect(trigger()).toHaveTextContent("Oct 7, 2026 3 PM");
    expect(trigger()).toHaveTextContent("Oct 14, 2026 11 PM");
  });

  it("offers Custom and Infloww's four Last N days by default, and a page's own presets and labels", () => {
    const { unmount } = render(<DateRangePicker from={null} to={null} preset="30d" onChange={() => {}} />);
    const presets = within(open()).getByRole("group", { name: "Date presets" });
    expect(within(presets).getAllByRole("button").map((b) => b.textContent))
      .toEqual(["Custom", "Last 7 days", "Last 30 days", "Last 90 days", "Last 365 days"]);
    expect(within(presets).getByRole("button", { name: "Last 30 days" })).toHaveAttribute("aria-pressed", "true");
    unmount();

    render(<DateRangePicker from={null} to={null} preset="day" onChange={() => {}}
      presets={["day", "7d", "30d"]} labels={{ day: "Day", "7d": "Week", "30d": "Month" }} />);
    expect(within(open()).getAllByRole("button").map((b) => b.textContent)).toEqual(["Custom", "Day", "Week", "Month"]);
  });

  it("a preset calls back with its presetRange and the preset", () => {
    const onChange = vi.fn();
    render(<DateRangePicker from={null} to={null} preset="30d" onChange={onChange} />);
    fireEvent.click(within(open()).getByRole("button", { name: "Last 90 days" }));
    expect(onChange).toHaveBeenLastCalledWith(...presetRange("90d"), "90d");
    // 90 calendar days, today included.
    expect(presetRange("90d")).toEqual(["2026-07-17", "2026-10-14"]);
    fireEvent.click(screen.getByRole("button", { name: "Last 365 days" }));
    expect(onChange).toHaveBeenLastCalledWith("2025-10-15", "2026-10-14", "365d");
  });

  it("a typed date is Custom, keeping the side's hour, inside a year back to two days ahead", () => {
    const onChange = vi.fn();
    render(<DateRangePicker from="2026-10-07T15:00" to="2026-10-14" preset="7d" onChange={onChange} hours />);
    const dialog = open();
    const fromDate = within(dialog).getByLabelText("From date");
    expect(fromDate).toHaveAttribute("min", dateBounds()[0]);
    expect(dateBounds()).toEqual(["2025-10-14", "2026-10-16"]);
    expect(within(dialog).getByLabelText("To date")).toHaveAttribute("max", "2026-10-16");
    fireEvent.change(fromDate, { target: { value: "2026-10-01" } });
    expect(onChange).toHaveBeenLastCalledWith("2026-10-01T15:00", "2026-10-14", "custom");

    fireEvent.click(within(dialog).getByRole("combobox", { name: "To hour" }));
    fireEvent.click(screen.getByRole("option", { name: "9 AM" }));
    expect(onChange).toHaveBeenLastCalledWith("2026-10-07T15:00", "2026-10-14T09:00", "custom");
  });

  it("refuses a span of more than a year with Infloww's line", () => {
    const onChange = vi.fn();
    render(<DateRangePicker from="2026-10-07" to="2026-10-14" preset="7d" onChange={onChange} />);
    const dialog = open();
    // 2025-09-09 to 2026-10-14 is 400 days.
    fireEvent.change(within(dialog).getByLabelText("From date"), { target: { value: "2025-09-09" } });
    expect(onChange).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("alert")).toHaveTextContent(SPAN_LIMIT);
    expect(SPAN_LIMIT).toBe("Selected time frame cannot be more than a year");

    fireEvent.change(within(dialog).getByLabelText("From date"), { target: { value: "2026-10-01" } });
    expect(onChange).toHaveBeenLastCalledWith("2026-10-01", "2026-10-14", "custom");
    expect(within(dialog).queryByRole("alert")).toBeNull();

    // The bounds' own year, a year back to today, fits.
    fireEvent.change(within(dialog).getByLabelText("From date"), { target: { value: dateBounds()[0] } });
    expect(onChange).toHaveBeenLastCalledWith("2025-10-14", "2026-10-14", "custom");
  });

  it("fits a leap year's 366 days as one year", () => {
    const onChange = vi.fn();
    render(<DateRangePicker from="2028-02-01" to="2028-03-01" preset="custom" onChange={onChange} />);
    fireEvent.change(within(open()).getByLabelText("From date"), { target: { value: "2027-03-01" } });
    expect(onChange).toHaveBeenLastCalledWith("2027-03-01", "2028-03-01", "custom");
  });

  it("refuses a From after the To, hours included", () => {
    const onChange = vi.fn();
    render(<DateRangePicker from="2026-10-14" to="2026-10-14T10:00" preset="custom" onChange={onChange} hours />);
    const dialog = open();
    fireEvent.click(within(dialog).getByRole("combobox", { name: "From hour" }));
    fireEvent.click(screen.getByRole("option", { name: "3 PM" }));
    expect(onChange).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("alert")).toHaveTextContent(REVERSED);

    fireEvent.change(within(dialog).getByLabelText("From date"), { target: { value: "2026-10-15" } });
    expect(onChange).not.toHaveBeenCalled();

    // The same hour on both sides is that one hour.
    fireEvent.click(within(dialog).getByRole("combobox", { name: "From hour" }));
    fireEvent.click(screen.getByRole("option", { name: "10 AM" }));
    expect(onChange).toHaveBeenLastCalledWith("2026-10-14T10:00", "2026-10-14T10:00", "custom");
    expect(within(dialog).queryByRole("alert")).toBeNull();
  });

  it("closes on Escape and on a click outside", () => {
    render(<div><p>outside</p><DateRangePicker from={null} to={null} preset="30d" onChange={() => {}} /></div>);
    fireEvent.keyDown(open(), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    open();
    fireEvent.mouseDown(screen.getByText("outside"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
