/** "Desktop update available": desktop shell only, older shell only, closed per latest version. */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { LATEST_DESKTOP_VERSION } from "@/lib/desktopVersion";
import { DesktopUpdateBanner } from "./DesktopUpdateBanner";

const setShell = (version: string) => { window.fasttShell = { isDesktop: true, platform: "darwin", version }; };

beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); delete window.fasttShell; });

describe("DesktopUpdateBanner", () => {
  it("shows in an older desktop shell with a link to /download, and stays closed once closed", () => {
    setShell("0.1.0");
    render(<DesktopUpdateBanner />);
    expect(screen.getByRole("status")).toHaveTextContent(`Desktop update available (v${LATEST_DESKTOP_VERSION})`);
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", "/download");
    fireEvent.click(screen.getByRole("button", { name: "Close update banner" }));
    expect(screen.queryByRole("status")).toBeNull();
    expect(localStorage.getItem("chatterly:desktop-update-closed")).toBe(LATEST_DESKTOP_VERSION);
    cleanup();
    render(<DesktopUpdateBanner />);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows again when closed for an earlier latest version", () => {
    localStorage.setItem("chatterly:desktop-update-closed", "0.0.1");
    setShell("0.1.0");
    render(<DesktopUpdateBanner />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("stays hidden on the web, in an up-to-date shell, and when the shell's version is unknown", () => {
    render(<DesktopUpdateBanner />);
    expect(screen.queryByRole("status")).toBeNull();
    cleanup();
    setShell(LATEST_DESKTOP_VERSION);
    render(<DesktopUpdateBanner />);
    expect(screen.queryByRole("status")).toBeNull();
    cleanup();
    setShell("unknown");
    render(<DesktopUpdateBanner />);
    expect(screen.queryByRole("status")).toBeNull();
  });
});
