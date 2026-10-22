/**
 * BrowserbaseLoginCard — the operator-facing states of the served Browserbase login.
 *
 *   - the copy says the login runs on Browserbase's network, needs no extension, and names the flow's proxy;
 *   - no proxy picker of its own: the start sends the flow's Proxy selection (the Inflowwww proxy, or a custom label);
 *   - a success names the attached proxy and hands the account on at once (onLinked), like Paste cURL;
 *   - while the job runs the form is replaced by plain-language progress, the live view, a full-screen link and Stop login;
 *   - a refused start reads "Couldn't start the login: …".
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (orig) => {
  const real = await orig<typeof import("@/lib/relay")>();
  return { ...real, relay: { get: vi.fn(), post: vi.fn() } };
});

import BrowserbaseLoginCard, { type RemoteLoginStatus } from "@/components/setup/BrowserbaseLoginCard";
import type { ProxyChoice } from "@/components/setup/creatorFlow";
import { relay, RelayError } from "@/lib/relay";
const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const job = (over: Partial<RemoteLoginStatus>): RemoteLoginStatus => ({
  id: "job1", backend: "browserbase", state: "starting", message: "", error: null, account_id: null,
  session_file: null, proxy: "custom", proxy_label: "isp-1", live_view_url: null,
  expires_at: 0, ...over,
});

let current: RemoteLoginStatus;
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  relayGet.mockReset();
  relayPost.mockReset();
  relayGet.mockImplementation((path: string) =>
    Promise.resolve(path === "/admin/proxies"
      ? { proxies: [{ label: "isp-1", scheme: "http", host: "203.0.113.9", port: 12323 }], pool: { size: 3, account_ids: [] } }
      : current));
  relayPost.mockImplementation(() => Promise.resolve(job({})));
});
afterEach(() => cleanup());

const CUSTOM: ProxyChoice = { type: "custom", label: "isp-1", ok: true };

function start(onLinked = vi.fn(), proxy: ProxyChoice = CUSTOM) {
  render(<BrowserbaseLoginCard onLinked={onLinked} proxy={proxy} />, { wrapper });
  fireEvent.change(screen.getByLabelText("OnlyFans email"), { target: { value: "a@b.c" } });
  fireEvent.change(screen.getByLabelText("OnlyFans password"), { target: { value: "pw" } });
  fireEvent.click(screen.getByRole("button", { name: "Try Browserbase login" }));
  return onLinked;
}

describe("BrowserbaseLoginCard", () => {
  it("says the login runs on Browserbase's network with no extension, and names the flow's proxy", async () => {
    render(<BrowserbaseLoginCard proxy={{ type: "infloww" }} />, { wrapper });
    expect(screen.getByText(/The login runs in a remote browser on Browserbase's network, so no extension is needed and it works on a\s+phone\./)).toBeInTheDocument();
    expect(screen.getByText("Proxy for this account:").parentElement).toHaveTextContent("Proxy for this account: Inflowwww proxy");
    // No proxy picker of its own: the flow's Proxy selection is the one.
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByText(/No proxies yet/)).toBeNull();
  });

  it("starts with the flow's Inflowwww proxy, and with a custom proxy by its label", async () => {
    start(vi.fn(), { type: "infloww" });
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/login/remote/start", {
      email: "a@b.c", password: "pw", backend: "browserbase", proxy: "infloww", proxy_label: undefined, nickname: undefined,
    }));
    cleanup();
    relayPost.mockClear();
    start();
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/login/remote/start", expect.objectContaining({
      proxy: "custom", proxy_label: "isp-1",
    })));
  });

  it("starts without any proxy registered: Try is enabled once email and password are in", () => {
    relayGet.mockImplementation((path: string) =>
      Promise.resolve(path === "/admin/proxies" ? { proxies: [], pool: { size: 0, account_ids: [] } } : current));
    render(<BrowserbaseLoginCard proxy={{ type: "none" }} />, { wrapper });
    const go = screen.getByRole("button", { name: "Try Browserbase login" });
    expect(go).toBeDisabled();
    fireEvent.change(screen.getByLabelText("OnlyFans email"), { target: { value: "a@b.c" } });
    fireEvent.change(screen.getByLabelText("OnlyFans password"), { target: { value: "pw" } });
    expect(go).toBeEnabled();
  });

  it("names the Inflowwww proxy on success", async () => {
    current = job({ state: "done", account_id: "778", proxy: "infloww", proxy_label: "" });
    start(vi.fn(), { type: "infloww" });
    expect(await screen.findByText("Account 778 added. The Inflowwww proxy is attached for all later traffic.")).toBeInTheDocument();
  });

  it("names the attached proxy and hands the account on at once", async () => {
    current = job({ state: "done", account_id: "777" });
    const onLinked = start();
    await waitFor(() => expect(onLinked).toHaveBeenCalledWith("777"));
    expect(screen.getByText("Account 777 added. Proxy isp-1 is attached for all later traffic.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();
  });

  it("replaces the form with progress, the live view and Stop login while the job runs", async () => {
    current = job({ state: "challenge", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    start();
    expect(await screen.findByText("OnlyFans is showing a verification check. Solve it in the live view.")).toBeInTheDocument();
    expect(screen.getByTitle("Browserbase live view")).toHaveAttribute("src", current.live_view_url);
    const full = screen.getByRole("link", { name: /Open live view full screen/ });
    expect(full).toHaveAttribute("href", current.live_view_url);
    expect(full).toHaveAttribute("target", "_blank");
    expect(screen.queryByLabelText("OnlyFans password")).toBeNull();
    expect(screen.queryByText(/The login runs in a remote browser/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Stop login" }));
    expect(relayPost).toHaveBeenLastCalledWith("/admin/login/remote/job1/cancel");
  });

  it("says a refused start couldn't start", async () => {
    relayPost.mockImplementation(() => Promise.reject(new RelayError(503, {}, "BROWSERBASE_API_KEY is not set")));
    start();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't start the login: BROWSERBASE_API_KEY is not set");
  });
});
