import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { IfDateInput } from "./ifDateInput";

function Controlled({ type, initial, onValue, ...rest }: {
  type: "date" | "time" | "datetime-local"; initial: string; onValue: (v: string) => void; min?: string; step?: number;
}) {
  const [v, setV] = useState(initial);
  return <IfDateInput aria-label="When" type={type} value={v} {...rest} onChange={(e) => { setV(e.target.value); onValue(e.target.value); }} />;
}

describe("IfDateInput", () => {
  it("keeps the native input: same type, value and fireEvent.change", () => {
    const onValue = vi.fn();
    render(<Controlled type="date" initial="2026-11-13" onValue={onValue} />);
    const input = screen.getByLabelText("When") as HTMLInputElement;
    expect(input.type).toBe("date");
    fireEvent.change(input, { target: { value: "2026-11-20" } });
    expect(onValue).toHaveBeenLastCalledWith("2026-11-20");
    expect(input.value).toBe("2026-11-20");
  });

  it("opens a themed calendar on click; a day emits the native value and closes it", () => {
    const onValue = vi.fn();
    render(<Controlled type="date" initial="2026-11-13" onValue={onValue} min="2026-11-05" />);
    const input = screen.getByLabelText("When") as HTMLInputElement;
    fireEvent.click(input);
    const panel = screen.getByRole("dialog", { name: "Choose date" });
    expect(panel).toHaveTextContent("Nov 2026");
    expect(screen.getByRole("button", { name: "2026-11-13" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "2026-11-04" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "2026-11-21" }));
    expect(onValue).toHaveBeenLastCalledWith("2026-11-21");
    expect(input.value).toBe("2026-11-21");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("pages months", () => {
    render(<Controlled type="date" initial="2026-01-15" onValue={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("When"));
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Dec 2025");
  });

  it("date-time: a day keeps the time, an hour keeps the day, the step limits minutes", () => {
    const onValue = vi.fn();
    render(<Controlled type="datetime-local" initial="2026-11-13T09:30" onValue={onValue} step={3600} />);
    fireEvent.click(screen.getByLabelText("When"));
    fireEvent.click(screen.getByRole("button", { name: "2026-11-14" }));
    expect(onValue).toHaveBeenLastCalledWith("2026-11-14T09:30");
    fireEvent.click(screen.getByRole("button", { name: "Hour 17" }));
    expect(onValue).toHaveBeenLastCalledWith("2026-11-14T17:30");
    expect(screen.getAllByRole("button", { name: /^Minute / })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("time: hour and minute columns; Escape closes", () => {
    const onValue = vi.fn();
    render(<Controlled type="time" initial="" onValue={onValue} />);
    const input = screen.getByLabelText("When");
    fireEvent.click(input);
    expect(screen.getByRole("dialog", { name: "Choose time" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Minute 45" }));
    expect(onValue).toHaveBeenLastCalledWith("00:45");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("stays shut when disabled", () => {
    render(<IfDateInput aria-label="When" type="date" disabled defaultValue="" />);
    fireEvent.click(screen.getByLabelText("When"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
