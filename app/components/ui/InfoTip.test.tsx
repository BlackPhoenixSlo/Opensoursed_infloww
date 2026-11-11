import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { InfoTip, placeTip } from "./InfoTip";

describe("placeTip", () => {
  const tip = { width: 200, height: 40 };
  it.each([
    ["above, centred", { top: 300, bottom: 314, left: 500, width: 14 }, 1200, { left: 407, top: 254 }],
    ["below when no room above", { top: 20, bottom: 34, left: 500, width: 14 }, 1200, { left: 407, top: 40 }],
    ["clamped at the left edge", { top: 300, bottom: 314, left: 2, width: 14 }, 1200, { left: 8, top: 254 }],
    ["clamped at the right edge", { top: 300, bottom: 314, left: 1190, width: 14 }, 1200, { left: 992, top: 254 }],
  ])("%s", (_, trigger, vw, want) => {
    expect(placeTip(trigger, tip, vw)).toEqual(want);
  });
});

describe("InfoTip", () => {
  it("names the icon by its text and shows no tip until asked", () => {
    render(<InfoTip text="What this counts" />);
    expect(screen.getByRole("img", { name: "What this counts" })).not.toHaveAttribute("title");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("opens on mouse hover, closes on leave", () => {
    render(<InfoTip text="What this counts" />);
    const icon = screen.getByRole("img", { name: "What this counts" });
    fireEvent.pointerEnter(icon, { pointerType: "mouse" });
    expect(screen.getByRole("tooltip")).toHaveTextContent("What this counts");
    expect(icon).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);
    fireEvent.pointerLeave(icon, { pointerType: "mouse" });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("opens on a tap and on focus; Escape and an outside tap close it", () => {
    render(<><InfoTip text="Tip" /><button type="button">elsewhere</button></>);
    const icon = screen.getByRole("img", { name: "Tip" });
    fireEvent.click(icon);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.focus(icon);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.pointerDown(screen.getByRole("button", { name: "elsewhere" }));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("keeps a separate accessible name when given one", () => {
    render(<InfoTip text="Long explanation" label="About this" />);
    fireEvent.click(screen.getByRole("img", { name: "About this" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Long explanation");
  });
});
