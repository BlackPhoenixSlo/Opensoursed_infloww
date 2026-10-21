/**
 * ChatterLogin's "Get the desktop app" card: a plain anchor to /download on the web, left out inside the
 * desktop app (desktop/preload.js sets `window.fasttShell.isDesktop`).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import ChatterLogin from "@/components/auth/ChatterLogin";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: null, clearUserLocally: vi.fn() }) }));
vi.mock("@/contexts/ChatterContext", () => ({
  useChatter: () => ({ chatter: null, login: vi.fn(), register: vi.fn() }),
}));

const shell = window as Window & { fasttShell?: { isDesktop: boolean } };
afterEach(() => {
  cleanup();
  delete shell.fasttShell;
});

describe("ChatterLogin desktop app card", () => {
  it("links to /download on the web", () => {
    renderWithProviders(<ChatterLogin />);
    expect(screen.getByRole("link", { name: /Get the desktop app/ })).toHaveAttribute("href", "/download");
  });

  it("is left out inside the desktop app", () => {
    shell.fasttShell = { isDesktop: true };
    renderWithProviders(<ChatterLogin />);
    expect(screen.queryByRole("link", { name: /Get the desktop app/ })).toBeNull();
    expect(document.querySelector('a[href="/download"]')).toBeNull();
  });
});
