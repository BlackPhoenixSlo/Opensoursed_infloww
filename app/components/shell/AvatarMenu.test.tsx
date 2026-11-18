/**
 * The avatar (profile) menu offers the desktop app: a plain anchor to /download on the web, left out inside the
 * desktop app (desktop/preload.js sets `window.fasttShell.isDesktop`).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import { AvatarMenu } from "@/components/shell/TopBar";

vi.mock("@/lib/events", () => ({ eventBus: { setScope: vi.fn(), on: () => () => {}, onStateChange: () => () => {} } }));
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: { username: "owner" }, logout: vi.fn() }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter: null, logout: vi.fn() }) }));

const shell = window as Window & { fasttShell?: { isDesktop: boolean } };
afterEach(() => {
  cleanup();
  delete shell.fasttShell;
});

const openMenu = () => {
  renderWithProviders(<AvatarMenu />);
  fireEvent.click(screen.getByRole("button", { name: "Account menu" }));
};

describe("AvatarMenu desktop app download", () => {
  it("links to /download on the web", () => {
    openMenu();
    expect(screen.getByRole("link", { name: /Download desktop app/ })).toHaveAttribute("href", "/download");
  });

  it("is left out inside the desktop app", () => {
    shell.fasttShell = { isDesktop: true };
    openMenu();
    expect(screen.queryByRole("link", { name: /Download desktop app/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Log out" })).toBeInTheDocument();
  });
});
