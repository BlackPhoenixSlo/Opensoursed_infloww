/** ImportCaptionsButton in a dialog: Escape in its panel closes the panel only, never the dialog around it. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ImportCaptionsButton } from "@/components/compose/ImportCaptionsButton";
import { IfModal } from "@/components/ui/infloww";

afterEach(() => cleanup());

describe("ImportCaptionsButton", () => {
  it("Escape in the paste box closes the panel, focus back on its trigger; the dialog stays", () => {
    const onClose = vi.fn();
    render(<IfModal title="Compose" onClose={onClose}><ImportCaptionsButton current={[""]} onImport={() => {}} /></IfModal>);
    const trigger = screen.getByRole("button", { name: "Import captions" });
    fireEvent.click(trigger);
    const paste = screen.getByRole("textbox", { name: "Paste captions" });
    paste.focus();
    fireEvent.change(paste, { target: { value: "a\nb" } });
    fireEvent.keyDown(paste, { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "Paste captions" })).toBeNull();
    expect(trigger).toHaveFocus();
    expect(onClose).not.toHaveBeenCalled();
    // The panel gone, Escape is the dialog's again.
    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
