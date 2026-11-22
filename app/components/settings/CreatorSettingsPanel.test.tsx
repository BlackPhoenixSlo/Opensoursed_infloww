/**
 * CreatorSettingsPanel — the Creator a per-Creator Settings panel shows (OfConsentTab, OfmWritesTab): a link's
 * `?account=` when it is a session-backed Creator, else the one in scope, else the first; none: the empty text.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

const state = vi.hoisted(() => ({ scoped: null as string | null, accounts: [] as { id: string }[], loading: false }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: state.scoped }) }));
vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => state.accounts,
  useAccounts: () => ({ isLoading: state.loading }),
}));
vi.mock("@/components/settings/SettingsPanel", () => ({
  SettingsPanel: ({ title, children }: { title: string; children: ReactNode }) => <section aria-label={title}>{children}</section>,
}));
vi.mock("@/components/ui/infloww", () => ({
  IfCreatorSelect: () => null,
  EmptyState: ({ text }: { text: string }) => <p>{text}</p>,
}));

import { CreatorSettingsPanel } from "@/components/settings/CreatorSettingsPanel";

afterEach(() => { cleanup(); Object.assign(state, { scoped: null, accounts: [], loading: false }); });

const show = (linked?: string | null) => render(
  <CreatorSettingsPanel title="T" emptyText="Pick one" linked={linked} card={(id) => <p data-testid="card">{id}</p>} />);

describe("CreatorSettingsPanel", () => {
  it.each([
    ["a linked session-backed Creator wins", { scoped: "b", accounts: [{ id: "a" }, { id: "c" }] }, "c", "c"],
    ["a linked Creator not session-backed: the one in scope", { scoped: "b", accounts: [{ id: "a" }] }, "z", "b"],
    ["no link, none in scope: the first", { scoped: null, accounts: [{ id: "a" }, { id: "c" }] }, null, "a"],
  ])("%s", (_name, s, linked, want) => {
    Object.assign(state, s);
    show(linked);
    expect(screen.getByTestId("card").textContent).toBe(want);
  });

  it("no Creator: the empty text (none while accounts load)", () => {
    show();
    expect(screen.getByText("Pick one")).toBeTruthy();
    cleanup();
    state.loading = true;
    show();
    expect(screen.queryByText("Pick one")).toBeNull();
  });
});
