/**
 * ScopeSelect — the below-lg creator picker (OF Manager, Messages Pro) now that the top bar has no model filter:
 * "All creators" then each creator, reading and writing ScopeContext; `pickAll` stands in for the plain All pick.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const { state } = vi.hoisted(() => ({
  state: { scope: { kind: "all" } as { kind: "all" } | { kind: "model"; accountId: string }, setScope: vi.fn() },
}));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => state }));

import { ScopeSelect } from "@/components/shell/ScopeSelect";
import type { AccountMeta } from "@/lib/relay";

const accounts = [{ id: "a1", nickname: "isa" }, { id: "a2", nickname: "" }] as AccountMeta[];

describe("ScopeSelect", () => {
  it("shows the scope and picks a creator, then All creators", () => {
    state.scope = { kind: "all" };
    state.setScope.mockReset();
    const onPicked = vi.fn();
    render(<ScopeSelect accounts={accounts} onPicked={onPicked} />);
    const trigger = screen.getByRole("combobox", { name: "Creator" });
    expect(trigger).toHaveTextContent("All creators");
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("option", { name: "a2" }));
    expect(state.setScope).toHaveBeenLastCalledWith({ kind: "model", accountId: "a2" });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("option", { name: "All creators" }));
    expect(state.setScope).toHaveBeenLastCalledWith({ kind: "all" });
    expect(onPicked).toHaveBeenCalledTimes(2);
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
});
