import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { Menu } from "./Menu";

afterEach(cleanup);

describe("Menu", () => {
  it("Escape closes it (the Vault rail's folder ⋯ menu); other keys don't", () => {
    render(<Menu label="⋯" ariaLabel="Folder actions" items={[{ label: "Download folder" }]} />);
    fireEvent.click(screen.getByRole("button", { name: "Folder actions" }));
    expect(screen.getByRole("menu")).toBeTruthy();
    fireEvent.keyDown(document, { key: "a" });
    expect(screen.getByRole("menu")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("Menu: the row menus' options (custom trigger, keys, danger, position)", () => {
  const items = (pick: (s: string) => void) => [
    { label: "Run now", onClick: () => pick("run") },
    { label: "Edit", disabled: true },
    { label: "Delete", danger: true, onClick: () => pick("delete") },
  ];
  const trigger = (p: object) => <button type="button" aria-label="More actions for A" {...p}>⋯</button>;

  it("draws the caller's trigger; arrows skip disabled items and wrap; Escape closes and refocuses the trigger", () => {
    render(<Menu trigger={trigger} menuLabel="Row" items={items(() => {})} />);
    const btn = screen.getByRole("button", { name: "More actions for A" });
    fireEvent.click(btn);
    const menu = screen.getByRole("menu", { name: "Row" });
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement?.textContent).toBe("Run now");
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement?.textContent).toBe("Delete");
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement?.textContent).toBe("Run now");
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(btn);
  });

  it("a pick closes, refocuses the trigger and runs the item; danger is red, disabled is dim", () => {
    const picked: string[] = [];
    render(<Menu trigger={trigger} items={items((s) => picked.push(s))} />);
    fireEvent.click(screen.getByRole("button", { name: "More actions for A" }));
    expect(screen.getByRole("menuitem", { name: "Delete" }).className).toContain("text-err");
    expect(screen.getByRole("menuitem", { name: "Edit" }).className).toContain("text-fg-dim");
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    expect(picked).toEqual(["delete"]);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "More actions for A" }));
  });

  it("`fixed` overlays the viewport under the trigger, right-aligned to it", () => {
    render(<Menu trigger={trigger} position="fixed" items={items(() => {})} />);
    const btn = screen.getByRole("button", { name: "More actions for A" });
    btn.getBoundingClientRect = () => ({ bottom: 100, right: window.innerWidth - 30 }) as DOMRect;
    fireEvent.click(btn);
    const menu = screen.getByRole("menu");
    expect(menu.className).toContain("fixed");
    expect(menu.style.top).toBe("104px");
    expect(menu.style.right).toBe("30px");
  });

  it("`flip` opens upward when the panel would hang past the viewport", () => {
    const orig = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = function () {
      return { bottom: this.getAttribute("role") === "menu" ? window.innerHeight + 50 : 10 } as DOMRect;
    };
    try {
      render(<Menu trigger={trigger} align="right" position="flip" items={items(() => {})} />);
      fireEvent.click(screen.getByRole("button", { name: "More actions for A" }));
      expect(screen.getByRole("menu").className).toContain("bottom-full");
    } finally {
      HTMLElement.prototype.getBoundingClientRect = orig;
    }
  });
});
