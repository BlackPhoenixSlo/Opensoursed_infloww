import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CopyButton } from "./CopyButton";

const setClipboard = (value: unknown) =>
  Object.defineProperty(navigator, "clipboard", { configurable: true, value });

describe("CopyButton", () => {
  afterEach(() => { vi.useRealTimers(); setClipboard(undefined); });

  it("copies, says so, then reads its label again after holdMs", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    render(<CopyButton text="KEY" label="Copy setup key" doneLabel="Copied" holdMs={1000} />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Copy setup key" })); });
    expect(writeText).toHaveBeenCalledWith("KEY");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(1000); });
    expect(screen.getByRole("button", { name: "Copy setup key" })).toBeInTheDocument();
  });

  it("never says Copied on an insecure origin (no clipboard) or a blocked write", async () => {
    setClipboard(undefined);
    const { unmount } = render(<CopyButton text="KEY" label="Copy" doneLabel="Copied" />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Copy" })); });
    expect(screen.queryByRole("button", { name: "Copied" })).toBeNull();
    unmount();
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error("blocked")) });
    render(<CopyButton text="KEY" label="Copy" doneLabel="Copied" />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Copy" })); });
    expect(screen.queryByRole("button", { name: "Copied" })).toBeNull();
  });

  it("bare: a plain button in a form copies without submitting it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    render(<form onSubmit={onSubmit}><CopyButton bare text="KEY" label="Copy" doneLabel="Copied" className="x" /></form>);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Copy" })); });
    expect(writeText).toHaveBeenCalledWith("KEY");
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Copied" })).toHaveClass("x");
  });
});
