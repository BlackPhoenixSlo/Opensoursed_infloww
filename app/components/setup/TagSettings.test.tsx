/**
 * TagSettings — the Tag column's gear and its Tag manager: each Tag with "used by N", Rename and Delete rewrite every
 * profile holding the Tag in one PUT of the `account` blob, other keys riding along; a refused blob (a chatter) leaves
 * the gear Not wired.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), put: vi.fn() }, RelayError: class extends Error {} }));

import TagSettings from "@/components/setup/TagSettings";
import { relay } from "@/lib/relay";
const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;

const BLOB = {
  agency_name: "Agency",
  creators: { profiles: { a1: { tag: "VIP", name: "Jade" }, a2: { tag: "VIP" }, a3: { tag: "New" } } },
};

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  relayGet.mockReset();
  relayPut.mockReset();
  relayGet.mockResolvedValue({ tab: "account", config: BLOB });
  relayPut.mockImplementation(async (_p: string, config: unknown) => ({ tab: "account", config }));
});
afterEach(() => { cleanup(); });

async function open() {
  render(<TagSettings />, { wrapper });
  const gear = screen.getByRole("button", { name: "Tag settings" });
  await waitFor(() => expect(gear).toBeEnabled());
  fireEvent.click(gear);
}

describe("TagSettings", () => {
  it("lists each Tag with how many creators use it", async () => {
    await open();
    expect(screen.getByText("VIP")).toBeInTheDocument();
    expect(screen.getByText("Used by 2 creators")).toBeInTheDocument();
    expect(screen.getByText("Used by 1 creator")).toBeInTheDocument();
  });

  it("renames a Tag on every profile that holds it, keeping the rest of the blob", async () => {
    await open();
    fireEvent.click(screen.getAllByRole("button", { name: "Rename" })[1]);
    fireEvent.change(screen.getByLabelText("Rename VIP"), { target: { value: " Top " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    expect(relayPut).toHaveBeenCalledWith("/admin/settings/account", {
      agency_name: "Agency",
      creators: { profiles: { a1: { tag: "Top", name: "Jade" }, a2: { tag: "Top" }, a3: { tag: "New" } } },
    });
    await waitFor(() => expect(screen.getByText("Top")).toBeInTheDocument());
  });

  it("refuses renaming onto another Tag's name, by Save and by Enter", async () => {
    await open();
    fireEvent.click(screen.getAllByRole("button", { name: "Rename" })[1]);
    const input = screen.getByLabelText("Rename VIP");
    fireEvent.change(input, { target: { value: "New" } });
    expect(screen.getByText("A tag with this name already exists")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(relayPut).not.toHaveBeenCalled();
  });

  it("deletes a Tag after asking, clearing it from its creators", async () => {
    await open();
    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    expect(screen.getByText("Remove this tag from 1 creator?")).toBeInTheDocument();
    // The asking row's own Delete (New sorts first).
    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    expect(relayPut.mock.calls[0][1].creators.profiles.a3).toEqual({});
    expect(relayPut.mock.calls[0][1].creators.profiles.a1).toEqual({ tag: "VIP", name: "Jade" });
  });

  it("is Not wired when the blob is refused", async () => {
    relayGet.mockRejectedValue(new Error("relay 401"));
    render(<TagSettings />, { wrapper });
    await waitFor(() => expect(relayGet).toHaveBeenCalled());
    const gear = screen.getByRole("button", { name: "Tag settings" });
    expect(gear).toBeDisabled();
    expect(gear).toHaveAttribute("title", "not wired");
  });
});
