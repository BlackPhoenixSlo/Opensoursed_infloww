import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { applyTheme, readOfDisplaySync, useOfTheme, writeOfDisplaySync } from "./ofMirrorTheme";

describe("applyTheme", () => {
  it("sets OF's dark mode class and its Dark mode switch", () => {
    document.body.innerHTML = `<input id="dark_mode_switcher" type="checkbox">`;
    const sw = document.getElementById("dark_mode_switcher") as HTMLInputElement;
    applyTheme(document, true);
    expect(document.documentElement.classList.contains("m-mode-dark")).toBe(true);
    expect(sw.checked).toBe(true);
    applyTheme(document, false);
    expect(document.documentElement.classList.contains("m-mode-dark")).toBe(false);
    expect(sw.checked).toBe(false);
  });
});

describe("useOfTheme — Synchronize platform display settings (OnlyFans)", () => {
  let frame: HTMLIFrameElement;
  const doc = () => frame.contentDocument!;
  const isDark = () => doc().documentElement.classList.contains("m-mode-dark");
  const flipSwitch = (on: boolean) => {
    const sw = doc().getElementById("dark_mode_switcher") as HTMLInputElement;
    sw.checked = on;
    act(() => { sw.dispatchEvent(new Event("change", { bubbles: true })); });
  };

  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = "";
    document.documentElement.setAttribute("data-theme", "dark");
    frame = document.createElement("iframe");
    document.body.appendChild(frame);
    doc().body.innerHTML = `<input id="dark_mode_switcher" type="checkbox">`;
  });
  afterEach(() => { frame.remove(); localStorage.clear(); });

  it("is on by default: the mirror follows our theme and its Dark mode switch sets ours", () => {
    expect(readOfDisplaySync()).toBe(true);
    const { result } = renderHook(() => useOfTheme({ current: frame }, "/x"));
    expect(result.current).toBe(true);
    expect(isDark()).toBe(true);
    flipSwitch(false);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("off: the mirror keeps OF's light look and its switch darkens only the mirror", () => {
    writeOfDisplaySync(false);
    const { result } = renderHook(() => useOfTheme({ current: frame }, "/x"));
    expect(result.current).toBe(false);
    expect(isDark()).toBe(false);
    flipSwitch(true);
    expect(result.current).toBe(true);
    expect(isDark()).toBe(true);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark"); // ours untouched
    flipSwitch(false);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(isDark()).toBe(false);
  });

  it("off: the mirror's own Dark mode outlives a remount of the frame", () => {
    writeOfDisplaySync(false);
    const first = renderHook(() => useOfTheme({ current: frame }, "/x"));
    flipSwitch(true);
    first.unmount();
    applyTheme(doc(), false); // a fresh page
    const { result } = renderHook(() => useOfTheme({ current: frame }, "/y"));
    expect(result.current).toBe(true);
    expect(isDark()).toBe(true);
  });

  it("turning it back on brings our theme back to the mirror", () => {
    writeOfDisplaySync(false);
    const { result } = renderHook(() => useOfTheme({ current: frame }, "/x"));
    expect(isDark()).toBe(false);
    act(() => writeOfDisplaySync(true));
    expect(result.current).toBe(true);
    expect(isDark()).toBe(true);
  });
});
