import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const roster = vi.hoisted(() => ({ accounts: [] as Array<{ id: string; nickname?: string }> }));
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => roster.accounts }));

import { AccountChips } from "@/components/AccountChips";

const TWO = [
  { id: "8000149", nickname: "ava" },
  { id: "8000186", nickname: "blake" },
];

beforeEach(() => {
  roster.accounts = TWO;
});
afterEach(cleanup);

describe("AccountChips", () => {
  it("renders nothing when there is only one account to pick", () => {
    roster.accounts = [{ id: "8000149", nickname: "ava" }];
    const { container } = render(<AccountChips accountId="8000149" onChange={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("still renders when the ONE pickable account is not the selected one", () => {
    roster.accounts = [{ id: "8000186", nickname: "blake" }];
    render(<AccountChips accountId="8000149" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "blake" })).toBeTruthy();
  });

  it("renders nothing when the roster has not loaded", () => {
    roster.accounts = [];
    const { container } = render(<AccountChips accountId={null} onChange={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("gives every account a chip, labelled by nickname and falling back to the id", () => {
    roster.accounts = [{ id: "8000149", nickname: "ava" }, { id: "8000186" }];
    render(<AccountChips accountId="8000149" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "ava" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "8000186" })).toBeTruthy();
  });

  it("hands back the account id, not the label it was rendered with", () => {
    const onChange = vi.fn();
    render(<AccountChips accountId="8000149" onChange={onChange} />);
    screen.getByRole("button", { name: "blake" }).click();
    expect(onChange.mock.calls).toEqual([["8000186"]]);
  });

  it("puts a caller's spacing on the row, never on the chips", () => {
    const { container } = render(
      <AccountChips accountId="8000149" onChange={() => {}} className="mb-3" />,
    );
    expect(container.firstElementChild?.className).toContain("mb-3");
    for (const b of screen.getAllByRole("button")) expect(b.className).not.toContain("mb-3");
  });
});
