/**
 * ChatterContext — `reprobe` (the gate's Retry after an outage): the cached
 * null from the outage is dropped, so `loading` holds until /chatter/me answers
 * again instead of the gate showing the sign-in form in between.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ChatterProvider, useChatter } from "@/contexts/ChatterContext";

function Probe() {
  const { chatter, loading, reprobe } = useChatter();
  return (
    <div>
      <span data-testid="state">{loading ? "loading" : chatter ? chatter.username : "none"}</span>
      <button onClick={reprobe}>Reprobe</button>
    </div>
  );
}

const CAROL = { chatter_id: "c1", username: "carol", display_name: null, color: null, owners: [] };
const res = (body: unknown, status = 200) =>
  ({ ok: status < 400, status, json: () => Promise.resolve(body) }) as unknown as Response;

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ChatterContext reprobe", () => {
  it("drops the outage's cached null: loading until /chatter/me answers again", async () => {
    let release!: () => void;
    const answer = new Promise<Response>((resolve) => { release = () => resolve(res(CAROL)); });
    fetchMock.mockImplementation((url: string) => {
      if (url !== "/chatter/me") return Promise.resolve(res([]));
      return fetchMock.mock.calls.filter(([u]) => u === "/chatter/me").length === 1
        ? Promise.resolve(res(null, 502))
        : answer;
    });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ChatterProvider><Probe /></ChatterProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("none")).toBeInTheDocument();

    act(() => { screen.getByRole("button", { name: "Reprobe" }).click(); });
    expect(await screen.findByText("loading")).toBeInTheDocument();

    await act(async () => { release(); await answer; });
    expect(await screen.findByText("carol")).toBeInTheDocument();
  });
});
