import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { IfModal } from "@/components/ui/infloww";
import ImageLightbox from "./ImageLightbox";

describe("ImageLightbox over a queue's IfModal", () => {
  function Queue({ onModalClose }: { onModalClose: () => void }) {
    const [zoom, setZoom] = useState(false);
    return (
      <IfModal title="Flags review" onClose={onModalClose}>
        <button type="button" onClick={() => setZoom(true)}>Zoom</button>
        {zoom && <ImageLightbox accountId="acct-1" mediaId={7} onClose={() => setZoom(false)} />}
      </IfModal>
    );
  }

  it("Escape closes only the lightbox, Tab stays in it, focus goes back to the zoom button", async () => {
    const onModalClose = vi.fn();
    render(<Queue onModalClose={onModalClose} />);
    const zoom = screen.getByRole("button", { name: "Zoom" });
    zoom.focus();
    fireEvent.click(zoom);
    const box = screen.getByRole("dialog", { name: "Image" });
    expect(box).toHaveFocus();
    for (let i = 0; i < 3; i++) {
      await userEvent.tab();
      expect(box).toContainElement(document.activeElement as HTMLElement);
    }
    const close = within(box).getByRole("button", { name: "Close" });
    expect(close).toHaveFocus();
    expect(close.querySelector("svg")).not.toBeNull();
    expect(close).not.toHaveTextContent("×");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Image" })).not.toBeInTheDocument();
    expect(onModalClose).not.toHaveBeenCalled();
    expect(zoom).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(onModalClose).toHaveBeenCalledTimes(1);
  });
});
