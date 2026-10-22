/**
 * BrowserbaseLoginCard — the operator-facing states of the served Browserbase login.
 *
 *   - the copy says the login runs on Browserbase's network and the proxy is attached afterwards;
 *   - a success names the attached proxy and hands the account on at once (onLinked), like Paste cURL;
 *   - while the job runs the form is replaced by plain-language progress, the live view and Cancel;
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
import { relay, RelayError } from "@/lib/relay";
const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const job = (over: Partial<RemoteLoginStatus>): RemoteLoginStatus => ({
  id: "job1", backend: "browserbase", state: "starting", message: "", error: null, account_id: null,
  session_file: null, proxy_label: "isp-1", live_view_url: null,
  expires_at: 0, ...over,
});

let current: RemoteLoginStatus;
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  relayGet.mockReset();
  relayPost.mockReset();
  relayGet.mockImplementation((path: string) =>
    Promise.resolve(path === "/admin/proxies" ? { proxies: [{ label: "isp-1", host: "203.0.113.9", port: 12323 }] } : current));
  relayPost.mockImplementation(() => Promise.resolve(job({})));
});
afterEach(() => cleanup());

function start(onLinked = vi.fn()) {
  render(<BrowserbaseLoginCard onLinked={onLinked} initialProxyLabel="isp-1" />, { wrapper });
  fireEvent.change(screen.getByLabelText("OnlyFans email"), { target: { value: "a@b.c" } });
  fireEvent.change(screen.getByLabelText("OnlyFans password"), { target: { value: "pw" } });
  fireEvent.click(screen.getByRole("button", { name: "Try Browserbase login" }));
  return onLinked;
}

describe("BrowserbaseLoginCard", () => {
  it("says the login runs on Browserbase's network and the proxy is attached afterwards", () => {
    render(<BrowserbaseLoginCard initialProxyLabel="isp-1" />, { wrapper });
    expect(screen.getByText(/The login runs in a remote browser on Browserbase's network\. The proxy you choose is attached to the\s+account for all later traffic\./)).toBeInTheDocument();
  });

  it("names the attached proxy and hands the account on at once", async () => {
    current = job({ state: "done", account_id: "777" });
    const onLinked = start();
    await waitFor(() => expect(onLinked).toHaveBeenCalledWith("777"));
    expect(screen.getByText("Account 777 added. Proxy isp-1 is attached for all later traffic.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();
  });

  it("replaces the form with progress, the live view and Cancel while the job runs", async () => {
    current = job({ state: "challenge", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    start();
    expect(await screen.findByText("OnlyFans is showing a verification check. Solve it in the live view.")).toBeInTheDocument();
    expect(screen.getByTitle("Browserbase live view")).toHaveAttribute("src", current.live_view_url);
    expect(screen.queryByLabelText("OnlyFans password")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(relayPost).toHaveBeenLastCalledWith("/admin/login/remote/job1/cancel");
  });

  it("says a refused start couldn't start", async () => {
    relayPost.mockImplementation(() => Promise.reject(new RelayError(503, {}, "BROWSERBASE_API_KEY is not set")));
    start();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't start the login: BROWSERBASE_API_KEY is not set");
  });
});
