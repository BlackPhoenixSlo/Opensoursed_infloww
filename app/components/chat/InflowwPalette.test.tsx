/**
 * InflowwPalette — the palette seam of
 * docs/spec/messages-pro-look-and-feel/phase-01-colour-and-shell.md (Testing
 * Decisions): the hook returns the palette style inside the wrapper and
 * nothing outside it, and a real portal root (`VaultPicker`) carries the
 * palette's custom properties on its outermost element inside the wrapper and
 * none outside it, so a picker reused outside Messages Pro keeps the app's
 * tokens. Expected values are the Colour inventory's
 * (docs/screenshots/messages-pro-compare.md).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";

import { InflowwPalette, useInflowwPalette } from "@/components/chat/InflowwPalette";
import { renderWithProviders } from "@/test-utils";
import { observerStub, resetComposerHarness, routeRelay } from "./composerTestHarness";
import { VaultPicker } from "./VaultPicker";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: { username: "owner" } }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter: null }) }));

function Probe() {
  const style = useInflowwPalette();
  return <div data-testid="probe" data-style={JSON.stringify(style ?? null)} />;
}

const probe = () => JSON.parse(screen.getByTestId("probe").getAttribute("data-style")!);

describe("InflowwPalette's hook", () => {
  it("returns nothing outside the wrapper", () => {
    renderWithProviders(<Probe />);
    expect(probe()).toBeNull();
  });

  it("returns the palette style inside the wrapper: Infloww's accent and shell, dark scheme", () => {
    renderWithProviders(<InflowwPalette><Probe /></InflowwPalette>);
    expect(probe()).toMatchObject({
      "--color-accent": "#4166f6",
      "--color-bg": "#151515",
      "--color-fg": "#d9d9d9",
      "--color-fg-dim": "#999999",
      "--inf-accent-text": "#7d97ff",
      "--inf-rule": "#444444",
      "--inf-bubble-in": "#262626",
      "--inf-ppv": "#232323",
      "--inf-action": "#666666",
      "--inf-liked": "#f0483e",
      "--inf-chip-text": "#e5e5e5",
      "--inf-fan-avatar": "#262626",
      "--inf-creator-avatar": "#666666",
      "--inf-list-avatar": "#666666",
      // Page-parity 07, sampled from the 2026-10-18 capture.
      "--inf-online": "#2ad4ac",
      "--inf-send-idle": "#666666",
      "--inf-send-idle-text": "#979797",
      "--inf-scripts-pill": "#353535",
      "--inf-ai-pill": "#243b42",
      "--inf-presence-text": "#8a8a8a",
      "--inf-presence-online": "#4aaa1a",
      colorScheme: "dark",
    });
  });

  it("under the app's light theme, returns Infloww's light set with a light scheme", () => {
    document.documentElement.setAttribute("data-theme", "light");
    try {
      const { container } = renderWithProviders(<InflowwPalette><Probe /></InflowwPalette>);
      expect(probe()).toMatchObject({
        "--color-accent": "#4166f6",
        "--color-bg": "#ffffff",
        "--color-fg": "#151515",
        "--inf-bubble-in": "#f5f5f5",
        colorScheme: "light",
      });
      expect((container.firstElementChild as HTMLElement).style.colorScheme).toBe("light");
    } finally {
      document.documentElement.removeAttribute("data-theme");
    }
  });

  it("the wrapper's own element carries the same custom properties", () => {
    const { container } = renderWithProviders(<InflowwPalette><Probe /></InflowwPalette>);
    const root = container.firstElementChild as HTMLElement;
    expect(root.style.getPropertyValue("--color-accent")).toBe("#4166f6");
    expect(root.style.getPropertyValue("--color-border")).toBe("#333333");
    expect(root.style.getPropertyValue("--inf-row-selected")).toBe("#353535");
    expect(root.style.colorScheme).toBe("dark");
  });
});

describe("a portal root (VaultPicker)", () => {
  beforeEach(() => {
    resetComposerHarness();
    vi.stubGlobal("IntersectionObserver", observerStub);
    routeRelay("/admin/vault-ai/cache/summary", () => ({ account_id: "acct-1", count: 0, running: false, last_run: null }));
    routeRelay("/api/of/v2/vault/lists", () => ({ list: [], hasMore: false }));
    routeRelay("/api/of/v2/vault/media", () => ({ list: [], hasMore: false }));
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  const picker = (
    <VaultPicker open onClose={() => {}} accountId="acct-1" initialSelectedIds={[]} onConfirm={() => {}} />
  );
  /** The picker's outermost element, the one portalled into <body>. */
  const pickerRoot = () => {
    const root = screen.getByRole("button", { name: "Close vault picker" }).parentElement!;
    expect(root.parentElement).toBe(document.body);
    return root;
  };
  const customProperties = (el: HTMLElement) =>
    Array.from(el.style).filter((name) => name.startsWith("--"));

  it("inside the wrapper, carries the palette's custom properties on its outermost element", () => {
    renderWithProviders(<InflowwPalette>{picker}</InflowwPalette>);
    const root = pickerRoot();
    expect(root.style.getPropertyValue("--color-accent")).toBe("#4166f6");
    expect(root.style.getPropertyValue("--color-panel")).toBe("#1c1c1c");
    expect(root.style.getPropertyValue("--color-fg")).toBe("#d9d9d9");
    expect(root.style.getPropertyValue("--inf-accent-text")).toBe("#7d97ff");
    expect(root.style.colorScheme).toBe("dark");
    // The backdrop keeps its own (transparent) fill: the palette paints no background on it.
    expect(root.style.background).toBe("");
  });

  it("outside the wrapper, carries none of them, so it keeps the app's tokens", () => {
    renderWithProviders(picker);
    const root = pickerRoot();
    expect(customProperties(root)).toEqual([]);
    expect(root.style.colorScheme).toBe("");
  });
});
