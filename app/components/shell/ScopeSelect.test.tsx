import { describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

const { state } = vi.hoisted(() => ({
  state: { scope: { kind: "all" } as { kind: "all" } | { kind: "model"; accountId: string }, setScope: vi.fn() },
}));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => state }));

import { ScopeSelect } from "@/components/shell/ScopeSelect";
import { AllPlatformsContext } from "@/lib/platform";
import type { AccountMeta } from "@/lib/relay";

const accounts = [{ id: "a1", nickname: "isa" }, { id: "a2", nickname: "" }] as AccountMeta[];

describe("ScopeSelect", () => {
  it("without pickAll offers no All creators and picks a creator", () => {
    state.scope = { kind: "model", accountId: "a1" };
    state.setScope.mockReset();
    const onPicked = vi.fn();
    render(<ScopeSelect accounts={accounts} onPicked={onPicked} />);
    const trigger = screen.getByRole("combobox", { name: "Creator" });
    expect(trigger).toHaveTextContent("isa");
    fireEvent.click(trigger);
    expect(screen.queryByRole("option", { name: "All creators" })).toBeNull();
    fireEvent.click(screen.getByRole("option", { name: "a2" }));
    expect(state.setScope).toHaveBeenLastCalledWith({ kind: "model", accountId: "a2" });
    expect(onPicked).toHaveBeenCalledOnce();
  });

  it("names the scoped creator, and All creators goes through pickAll when given", () => {
    state.scope = { kind: "model", accountId: "a1" };
    state.setScope.mockReset();
    const pickAll = vi.fn();
    render(<ScopeSelect accounts={accounts} pickAll={pickAll} />);
    const trigger = screen.getByRole("combobox", { name: "Creator" });
    expect(trigger).toHaveTextContent("isa");
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("option", { name: "All creators" }));
    expect(pickAll).toHaveBeenCalledOnce();
    expect(state.setScope).not.toHaveBeenCalled();
  });

  it("badges a Fansly creator inside Combined Messages Pro only, and searches her by name", () => {
    state.scope = { kind: "all" };
    const mixed = [{ id: "a1", nickname: "isa" }, { id: "f1", nickname: "nova", platform: "fansly" }] as AccountMeta[];
    const logos = () => {
      fireEvent.click(screen.getByRole("combobox", { name: "Creator" }));
      return screen.getAllByRole("option").map((o) => within(o).queryByTestId("platform-logo-fansly") !== null);
    };
    render(<ScopeSelect accounts={mixed} />);
    expect(logos()).toEqual([false, false]);
    cleanup();
    render(<AllPlatformsContext value><ScopeSelect accounts={mixed} /></AllPlatformsContext>);
    expect(logos()).toEqual([false, true]);
    expect(screen.getByRole("option", { name: /nova/ })).toBeInTheDocument();
  });
});
