/**
 * UserContext — focus / visibility revalidation (frontend-review-lows fix).
 *
 * Pre-fix, UserProvider fetched /auth/me ONLY once on mount, so a stale
 * impersonation overlay (another tab stopped impersonating, the cookie
 * expired) lingered until a hard reload. The fix adds a second effect that
 * re-validates /auth/me when the tab regains focus / becomes visible. These
 * tests pin that contract — and would all fail against the pre-fix code,
 * which has no focus/visibility listener at all:
 *   • a window "focus" re-fetches /auth/me and adopts the fresh user;
 *   • visibilitychange revalidates while VISIBLE but is a no-op while HIDDEN;
 *   • an already-in-flight revalidation is not double-fired by a second focus
 *     (the `inFlight` guard);
 *   • the revalidate never flips `loading` back on (so it can't reflash the
 *     picker).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { UserProvider, useUser } from "@/contexts/UserContext";
import { clearPersistedCache } from "@/lib/rqPersister";

vi.mock("@/lib/rqPersister", () => ({ clearPersistedCache: vi.fn(async () => {}) }));

type Body = { user_id?: string; username?: string } | null;
function jsonRes(body: Body, ok = true, status = ok ? 200 : 500) {
  return { ok, status, json: () => Promise.resolve(body) } as unknown as Response;
}

function Probe() {
  const { user, loading, boot, retry, clearUserLocally } = useUser();
  return (
    <div>
      <span data-testid="loading">{loading ? "loading" : "ready"}</span>
      <span data-testid="user">{user ? user.username : "none"}</span>
      <span data-testid="boot">{boot}</span>
      <button onClick={retry}>Retry</button>
      <button onClick={clearUserLocally}>Clear</button>
    </div>
  );
}

function renderProvider() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <UserProvider>
        <Probe />
      </UserProvider>
    </QueryClientProvider>,
  );
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, value: state });
}

const ALICE = { user_id: "u1", username: "alice" };
const BOB = { user_id: "u2", username: "bob" };

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  setVisibility("visible");
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("UserContext focus/visibility revalidation", () => {
  it("re-fetches /auth/me on window focus and adopts the fresh user", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes(ALICE)).mockResolvedValue(jsonRes(BOB));
    renderProvider();

    // Mount fetch settled → the one and only fetch so far.
    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    act(() => { window.dispatchEvent(new Event("focus")); });

    // The whole point of the fix: focus pulls a fresh /auth/me and swaps the
    // user in without a reload.
    expect(await screen.findByText("bob")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    // The revalidate never reflashes the picker: loading stays settled.
    expect(screen.getByTestId("loading")).toHaveTextContent("ready");
  });

  it("revalidates on visibilitychange while VISIBLE, but never while HIDDEN", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes(ALICE)).mockResolvedValue(jsonRes(BOB));
    renderProvider();
    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Hidden tab: neither a visibilitychange nor a focus should hit the network.
    setVisibility("hidden");
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
      window.dispatchEvent(new Event("focus"));
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("user")).toHaveTextContent("alice");

    // Back to visible: a visibilitychange now revalidates.
    setVisibility("visible");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(await screen.findByText("bob")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not double-fire while a revalidation is already in flight", async () => {
    let releaseFocus!: () => void;
    const pending = new Promise<Response>((resolve) => {
      releaseFocus = () => resolve(jsonRes(BOB));
    });
    fetchMock.mockResolvedValueOnce(jsonRes(ALICE)).mockReturnValueOnce(pending);
    renderProvider();
    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Two focus events back-to-back: the first starts the fetch and sets the
    // inFlight guard, so the second must be dropped (no second request).
    act(() => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("focus"));
    });
    expect(fetchMock).toHaveBeenCalledTimes(2); // mount + exactly one focus

    await act(async () => { releaseFocus(); await pending; });
    expect(await screen.findByText("bob")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2); // still no third fetch
  });
});

describe("UserContext logout", () => {
  it("waits for the persisted cache delete to commit before navigating away", async () => {
    let commit!: () => void;
    const realLocation = window.location;
    const replace = vi.fn();
    Object.defineProperty(window, "location", { configurable: true, value: { ...realLocation, replace } });
    try {
      fetchMock.mockResolvedValue(jsonRes(ALICE));
      let done = false;
      function LogoutProbe() {
        const { logout } = useUser();
        return <button onClick={() => void logout().then(() => { done = true; })}>Log out</button>;
      }
      render(
        <QueryClientProvider client={new QueryClient()}>
          <UserProvider><LogoutProbe /></UserProvider>
        </QueryClientProvider>,
      );

      await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
      await act(async () => { await Promise.resolve(); });
      vi.mocked(clearPersistedCache).mockClear().mockReturnValueOnce(new Promise<void>((r) => { commit = r; }));

      act(() => { screen.getByRole("button", { name: "Log out" }).click(); });
      await vi.waitFor(() => expect(clearPersistedCache).toHaveBeenCalled());
      await act(async () => { await Promise.resolve(); });
      expect(replace).not.toHaveBeenCalled();

      await act(async () => { commit(); });
      await vi.waitFor(() => expect(done).toBe(true));
      expect(replace).toHaveBeenCalledWith("/");
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: realLocation });
    }
  });
});

describe("UserContext boot against an unreachable relay", () => {
  it.each<[string, () => Promise<Response>]>([
    ["the fetch throws", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["the proxy answers 500 (relay down behind the Next rewrite)", () => Promise.resolve(jsonRes(null, false, 500))],
  ])("%s: the retry state, not signed out; Retry signs in once it answers", async (_name, down) => {
    fetchMock.mockImplementationOnce(down).mockResolvedValue(jsonRes(ALICE));
    renderProvider();
    expect(await screen.findByText("unreachable")).toBeInTheDocument();
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expect(screen.getByTestId("loading")).toHaveTextContent("ready");

    act(() => { screen.getByRole("button", { name: "Retry" }).click(); });
    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(screen.getByTestId("boot")).toHaveTextContent("settled");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("a focus on the retry state probes nothing: only Retry re-runs the boot", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValue(jsonRes(ALICE));
    renderProvider();
    expect(await screen.findByText("unreachable")).toBeInTheDocument();
    act(() => {
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("boot")).toHaveTextContent("unreachable");
  });

  it("a hung boot probe times out into the retry state", async () => {
    // AbortSignal.timeout's timer, made firable by hand.
    const timeout = new AbortController();
    const spy = vi.spyOn(AbortSignal, "timeout").mockReturnValue(timeout.signal);
    try {
      fetchMock.mockImplementation((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      }));
      renderProvider();
      await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      expect(screen.getByTestId("boot")).toHaveTextContent("probing");
      expect(spy).toHaveBeenCalledWith(expect.any(Number));
      act(() => { timeout.abort(new DOMException("timed out", "TimeoutError")); });
      expect(await screen.findByText("unreachable")).toBeInTheDocument();
    } finally {
      spy.mockRestore();
    }
  });

  it("a 401 at boot is the sign-in form, not the retry state", async () => {
    fetchMock.mockResolvedValue(jsonRes(null, false, 401));
    renderProvider();
    expect(await screen.findByText("ready")).toBeInTheDocument();
    expect(screen.getByTestId("boot")).toHaveTextContent("settled");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
  });

  it("a network error on a focus revalidation keeps the user", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes(ALICE)).mockRejectedValue(new TypeError("Failed to fetch"));
    renderProvider();
    expect(await screen.findByText("alice")).toBeInTheDocument();
    act(() => { window.dispatchEvent(new Event("focus")); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    // A focus only probes once the previous one settled, so a third fetch
    // proves the rejection landed — and the user survived it.
    await vi.waitFor(() => {
      act(() => { window.dispatchEvent(new Event("focus")); });
      expect(fetchMock).toHaveBeenCalledTimes(3);
    });
    expect(screen.getByTestId("user")).toHaveTextContent("alice");
    expect(screen.getByTestId("boot")).toHaveTextContent("settled");
  });

  it("a revalidate answer landing after a local sign-out is dropped", async () => {
    let release!: () => void;
    const pending = new Promise<Response>((resolve) => { release = () => resolve(jsonRes(ALICE)); });
    fetchMock.mockResolvedValueOnce(jsonRes(ALICE)).mockReturnValueOnce(pending).mockResolvedValue(jsonRes(null));
    renderProvider();
    expect(await screen.findByText("alice")).toBeInTheDocument();
    act(() => { window.dispatchEvent(new Event("focus")); });
    expect(fetchMock).toHaveBeenCalledTimes(2);

    act(() => { screen.getByRole("button", { name: "Clear" }).click(); });
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    // A macrotask: every microtask of the late answer has run by then.
    await act(async () => { release(); await new Promise((r) => setTimeout(r, 0)); });
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    // The dropped probe no longer blocks the next focus.
    act(() => { window.dispatchEvent(new Event("focus")); });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("the boot effect re-running mid-revalidation neither drops the answer nor blocks the next focus", async () => {
    let release!: () => void;
    const pending = new Promise<Response>((resolve) => { release = () => resolve(jsonRes(BOB)); });
    fetchMock.mockResolvedValueOnce(jsonRes(ALICE)).mockReturnValueOnce(pending).mockResolvedValue(jsonRes(BOB));
    const tree = (qc: QueryClient) => (
      <QueryClientProvider client={qc}><UserProvider><Probe /></UserProvider></QueryClientProvider>
    );
    const { rerender } = render(tree(new QueryClient()));
    expect(await screen.findByText("alice")).toBeInTheDocument();
    act(() => { window.dispatchEvent(new Event("focus")); });
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // A new QueryClient re-creates `send`, so the boot effect re-runs.
    rerender(tree(new QueryClient()));
    await act(async () => { release(); await pending; });
    expect(await screen.findByText("bob")).toBeInTheDocument();
    act(() => { window.dispatchEvent(new Event("focus")); });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
