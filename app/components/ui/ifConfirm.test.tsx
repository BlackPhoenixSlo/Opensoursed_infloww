import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import { IfConfirmHost, ifAlert, ifConfirm } from "./ifConfirm";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ifConfirm with the host mounted", () => {
  it("draws the message with its line breaks, and OK (focused) resolves true", async () => {
    const native = vi.spyOn(window, "confirm");
    render(<IfConfirmHost />);
    let answer!: Promise<boolean>;
    act(() => { answer = ifConfirm("Delete it?\n\nNo undo.", { confirmLabel: "Delete", danger: true }); });
    const dialog = await screen.findByRole("dialog", { name: "Confirm" });
    expect(dialog.querySelector("p")).toHaveClass("whitespace-pre-line");
    expect(dialog.querySelector("p")?.textContent).toBe("Delete it?\n\nNo undo.");
    const ok = screen.getByRole("button", { name: "Delete" });
    expect(ok).toHaveFocus();
    expect(ok).toHaveClass("bg-err");
    fireEvent.click(ok);
    await expect(answer).resolves.toBe(true);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(native).not.toHaveBeenCalled();
  });

  it("Escape, Cancel and a mask click resolve false", async () => {
    render(<IfConfirmHost />);
    let answer!: Promise<boolean>;
    act(() => { answer = ifConfirm("Sure?"); });
    await screen.findByRole("dialog");
    fireEvent.keyDown(document, { key: "Escape" });
    await expect(answer).resolves.toBe(false);

    act(() => { answer = ifConfirm("Sure?"); });
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await expect(answer).resolves.toBe(false);

    act(() => { answer = ifConfirm("Sure?"); });
    const box = await screen.findByRole("dialog");
    fireEvent.click(box.parentElement!);
    await expect(answer).resolves.toBe(false);
  });

  it("asks one at a time, in order; ifAlert has OK only", async () => {
    render(<IfConfirmHost />);
    let first!: Promise<boolean>;
    let second!: Promise<void>;
    act(() => {
      first = ifConfirm("First?");
      second = ifAlert("Second.");
    });
    expect(await screen.findByText("First?")).toBeInTheDocument();
    expect(screen.queryByText("Second.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await expect(first).resolves.toBe(true);
    expect(await screen.findByText("Second.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await expect(second).resolves.toBeUndefined();
  });
});

describe("ifConfirm with no host", () => {
  it("falls back to window.confirm / window.alert", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const alert = vi.spyOn(window, "alert").mockImplementation(() => {});
    await expect(ifConfirm("Go?")).resolves.toBe(false);
    expect(confirm).toHaveBeenCalledWith("Go?");
    await ifAlert("Done.");
    expect(alert).toHaveBeenCalledWith("Done.");
  });

  it("falls back again once the host unmounts", async () => {
    const { unmount } = render(<IfConfirmHost />);
    unmount();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    await expect(ifConfirm("Go?")).resolves.toBe(true);
    expect(confirm).toHaveBeenCalledOnce();
  });
});
