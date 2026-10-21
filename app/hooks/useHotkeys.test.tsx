/**
 * useHotkeys — the Messages Pro shortcuts (gap 04 M17). The cases pin what a
 * chatter feels: a modifier not named keeps the binding off (Cmd+W must stay
 * the window close), `mod` takes Cmd or Ctrl, Ctrl+W still matches on a
 * layout whose W key types another letter, a matched key always loses its
 * default, and a held key fires once.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { matchesHotkey, useHotkeys, type Hotkey } from "./useHotkeys";

afterEach(cleanup);

function key(init: KeyboardEventInit): KeyboardEvent {
  return new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
}

function Probe({ bindings }: { bindings: Hotkey[] }) {
  useHotkeys(bindings);
  return null;
}

describe("matchesHotkey", () => {
  it("needs exactly the named modifiers", () => {
    expect(matchesHotkey("ctrl+w", key({ key: "w", code: "KeyW", ctrlKey: true }))).toBe(true);
    expect(matchesHotkey("ctrl+w", key({ key: "w", code: "KeyW", metaKey: true }))).toBe(false);
    expect(matchesHotkey("ctrl+w", key({ key: "W", code: "KeyW", ctrlKey: true, shiftKey: true }))).toBe(false);
    expect(matchesHotkey("ctrl+w", key({ key: "w", code: "KeyW" }))).toBe(false);
  });

  it("takes Cmd or Ctrl for mod, not both", () => {
    expect(matchesHotkey("mod+shift+s", key({ key: "S", code: "KeyS", metaKey: true, shiftKey: true }))).toBe(true);
    expect(matchesHotkey("mod+shift+s", key({ key: "S", code: "KeyS", ctrlKey: true, shiftKey: true }))).toBe(true);
    expect(matchesHotkey("mod+shift+s", key({ key: "S", code: "KeyS", ctrlKey: true, metaKey: true, shiftKey: true }))).toBe(false);
    expect(matchesHotkey("mod+shift+s", key({ key: "s", code: "KeyS", metaKey: true }))).toBe(false);
  });

  it("matches the physical key when the layout types a non-Latin letter, and the typed letter otherwise", () => {
    // Cyrillic (ЙЦУКЕН): the W key types "ц".
    expect(matchesHotkey("ctrl+w", key({ key: "ц", code: "KeyW", ctrlKey: true }))).toBe(true);
    // AZERTY: the key labelled W sits where QWERTY has Z.
    expect(matchesHotkey("ctrl+w", key({ key: "w", code: "KeyZ", ctrlKey: true }))).toBe(true);
    expect(matchesHotkey("ctrl+w", key({ key: "z", code: "KeyW", ctrlKey: true }))).toBe(false);
  });
});

describe("useHotkeys", () => {
  it("runs the binding and suppresses the default", () => {
    const run = vi.fn();
    render(<Probe bindings={[{ keys: "ctrl+w", run }]} />);
    const e = key({ key: "w", code: "KeyW", ctrlKey: true });
    window.dispatchEvent(e);
    expect(run).toHaveBeenCalledTimes(1);
    expect(e.defaultPrevented).toBe(true);
  });

  it("claims an auto-repeat without running the binding again; an unbound key keeps its default", () => {
    const run = vi.fn();
    render(<Probe bindings={[{ keys: "ctrl+w", run }]} />);
    const held = key({ key: "w", code: "KeyW", ctrlKey: true, repeat: true });
    window.dispatchEvent(held);
    expect(held.defaultPrevented).toBe(true);
    expect(run).not.toHaveBeenCalled();
    const other = key({ key: "q", code: "KeyQ", ctrlKey: true });
    window.dispatchEvent(other);
    expect(other.defaultPrevented).toBe(false);
  });

  it("leaves IME composition alone, and stops listening on unmount", () => {
    const run = vi.fn();
    const { unmount } = render(<Probe bindings={[{ keys: "ctrl+w", run }]} />);
    const composing = key({ key: "w", code: "KeyW", ctrlKey: true, isComposing: true });
    window.dispatchEvent(composing);
    expect(composing.defaultPrevented).toBe(false);
    unmount();
    window.dispatchEvent(key({ key: "w", code: "KeyW", ctrlKey: true }));
    expect(run).not.toHaveBeenCalled();
  });
});
