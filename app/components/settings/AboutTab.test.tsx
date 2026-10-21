/**
 * AboutTab — the About Inflowwww Panel (docs/spec/settings-tabs/phase-05-billing-balance-about.md,
 * Testing Decisions). `globalThis.fetch` is a spy set before every render, so "makes no request" is an
 * assertion about the wire.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import AboutTab from "@/components/settings/AboutTab";
import { version } from "@/package.json";

let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchSpy = vi.fn(async () => new Response("{}", { status: 404 }));
  vi.stubGlobal("fetch", fetchSpy);
});
const shell = window as Window & { fasttShell?: { isDesktop: boolean } };
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  delete shell.fasttShell;
});

describe("AboutTab", () => {
  it("is headed \"About\" and makes no request", () => {
    renderWithProviders(<AboutTab />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(/^About$/);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("shows \"Version \" plus the app's package.json version", () => {
    renderWithProviders(<AboutTab />);
    expect(screen.getByText(`Version ${version}`, { exact: true })).toBeInTheDocument();
  });

  it("shows an 88px Inflowwww logo", () => {
    renderWithProviders(<AboutTab />);
    const logo = screen.getByRole("img", { name: "Inflowwww" });
    expect(logo).toHaveClass("w-[88px]", "h-[88px]");
  });

  it("offers the desktop app in a box whose Download links to /download, as a plain anchor in the same tab", () => {
    renderWithProviders(<AboutTab />);
    expect(screen.getByText("Get the desktop app")).toBeInTheDocument();
    expect(screen.getByText("Inflowwww for Mac and Windows")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Download" });
    expect(link).toHaveAttribute("href", "/download");
    expect(link).not.toHaveAttribute("target");
  });

  it("leaves the desktop app box out inside the desktop app", () => {
    shell.fasttShell = { isDesktop: true };
    renderWithProviders(<AboutTab />);
    expect(screen.queryByText("Get the desktop app")).toBeNull();
    expect(screen.queryByRole("link", { name: "Download" })).toBeNull();
    expect(screen.getByRole("link", { name: "MIT License" })).toBeInTheDocument();
  });

  it("links to the MIT License on the public repo's main branch, in a new tab", () => {
    renderWithProviders(<AboutTab />);
    const link = screen.getByRole("link", { name: "MIT License" });
    expect(link.getAttribute("href")).toMatch(/^https:\/\/github\.com\/[^/]+\/[^/]+\/blob\/main\/LICENSE$/);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows no beta box and no build hash", () => {
    const { container } = renderWithProviders(<AboutTab />);
    expect(container.textContent).not.toMatch(/beta/i);
    expect(container.textContent).not.toMatch(/build|commit|\b[0-9a-f]{7,40}\b/i);
  });
});
