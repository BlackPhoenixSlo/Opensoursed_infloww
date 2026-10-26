/**
 * BrowserbaseLoginCard — the operator-facing states of the served Browserbase login.
 *
 *   - the copy says the login runs on Browserbase's network, needs no extension, and names the flow's proxy; on a phone
 *     that explanation folds behind "How it works" so the form and its button fit the first screen;
 *   - no proxy picker of its own: the start sends the flow's Proxy selection (the Inflowwww proxy, or a custom label);
 *   - a success names the attached proxy and hands the account on at once (onLinked), like Paste cURL;
 *   - while the job runs the form is replaced by plain-language progress, the live view, a full-screen link and Stop login;
 *   - a refused start reads "Couldn't start the login: …";
 *   - on OnlyFans' 2FA prompt ("otp") a numeric code field (autofocused, 6-8 digits) and Submit code appear above the
 *     live view; Submit POSTs {code} to /admin/login/remote/{id}/otp; a code OnlyFans rejected, one the relay couldn't
 *     type, or a refused POST, shows an error and the field takes another code; the field is locked while the code is
 *     in flight and while OnlyFans checks it (a poll read before the code was in never unlocks it); leaving the prompt
 *     (or a new job) clears the typed code and the error;
 *   - the field drops only spaces and dashes: a pasted "1234-5678" is the 8-digit code, anything else stays visibly
 *     wrong (Submit off) instead of turning into another code.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("folds the explanation behind How it works on a phone, so the form fits the first screen", () => {
    render(<BrowserbaseLoginCard proxy={{ type: "infloww" }} />, { wrapper });
    const how = screen.getByRole("button", { name: "How it works" });
    const text = screen.getByText(/The login runs in a remote browser/);
    expect(how).toHaveClass("md:hidden");
    expect(how).toHaveAttribute("aria-expanded", "false");
    expect(text).toHaveClass("max-md:hidden");
    fireEvent.click(how);
    expect(how).toHaveAttribute("aria-expanded", "true");
    expect(text).not.toHaveClass("max-md:hidden");
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

  it("asks for the 2FA code on the card, keeps the live view, and posts the code to the job's otp route", async () => {
    current = job({ state: "otp", message: "OnlyFans asks for the 2FA code", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    start();
    expect(await screen.findByText("OnlyFans is asking for the 2FA code. Enter it below (or in the live view).")).toBeInTheDocument();
    const field = screen.getByLabelText("2FA code");
    expect(field).toHaveFocus();
    expect(field).toHaveAttribute("inputmode", "numeric");
    expect(screen.getByTitle("Browserbase live view")).toHaveAttribute("src", current.live_view_url);
    const submit = screen.getByRole("button", { name: "Submit code" });
    fireEvent.change(field, { target: { value: "12 3a" } });
    expect(field).toHaveValue("123a");
    expect(submit).toBeDisabled();
    fireEvent.change(field, { target: { value: "123456" } });
    relayPost.mockImplementation(() => Promise.resolve(job({ state: "otp", message: "checking the 2FA code" })));
    fireEvent.click(submit);
    await waitFor(() => expect(relayPost).toHaveBeenLastCalledWith("/admin/login/remote/job1/otp", { code: "123456" }));
    expect(await screen.findByText("Checking the code with OnlyFans…")).toBeInTheDocument();
    expect(screen.getByLabelText("2FA code")).toHaveValue("");
  });

  it("shows a rejected code and a refused POST as errors, and takes another code", async () => {
    current = job({ state: "otp", message: "OnlyFans didn't accept that code (or hasn't answered yet) — try again", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    start();
    expect(await screen.findByRole("alert")).toHaveTextContent("OnlyFans didn't accept that code (or hasn't answered yet). Check it and try again.");
    const field = screen.getByLabelText("2FA code");
    fireEvent.change(field, { target: { value: "654321" } });
    relayPost.mockImplementation(() => Promise.reject(new RelayError(409, {}, "the login is not waiting for a 2FA code (state: typing)")));
    fireEvent.click(screen.getByRole("button", { name: "Submit code" }));
    await waitFor(() => expect(relayPost).toHaveBeenLastCalledWith("/admin/login/remote/job1/otp", { code: "654321" }));
    expect(await screen.findByText("Couldn't send the code: the login is not waiting for a 2FA code (state: typing)")).toBeInTheDocument();
    expect(screen.getByLabelText("2FA code")).toHaveValue("654321");
    expect(screen.getByRole("button", { name: "Submit code" })).toBeEnabled();
  });

  it("locks the field while the code is in flight", async () => {
    current = job({ state: "otp", message: "OnlyFans asks for the 2FA code", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    start();
    const field = await screen.findByLabelText("2FA code");
    fireEvent.change(field, { target: { value: "123456" } });
    let answer: (j: RemoteLoginStatus) => void = () => {};
    relayPost.mockImplementation(() => new Promise<RemoteLoginStatus>((ok) => { answer = ok; }));
    fireEvent.click(screen.getByRole("button", { name: "Submit code" }));
    expect(await screen.findByRole("button", { name: "Sending…" })).toBeDisabled();
    expect(field).toBeDisabled();
    fireEvent.submit(field.closest("form")!);
    expect(relayPost.mock.calls.filter(([p]) => p === "/admin/login/remote/job1/otp")).toHaveLength(1);
    await act(async () => answer(job({ state: "otp", message: "checking the 2FA code" })));
    expect(await screen.findByText("Checking the code with OnlyFans…")).toBeInTheDocument();
    expect(screen.getByLabelText("2FA code")).toBeDisabled(); // still locked while OnlyFans checks it
    expect(screen.getByLabelText("2FA code")).toHaveValue("");
    current = job({ state: "otp", message: "OnlyFans didn't accept that code (or hasn't answered yet) — try again", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    await act(async () => { await client.refetchQueries({ queryKey: ["remote-login", "job1"] }); });
    await waitFor(() => expect(screen.getByLabelText("2FA code")).toBeEnabled());
  });

  it("keeps the field locked when a poll read before the code was in lands after the POST", async () => {
    current = job({ state: "otp", message: "OnlyFans asks for the 2FA code — enter it here or in the live view", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    start();
    const field = await screen.findByLabelText("2FA code");
    let stale: (j: RemoteLoginStatus) => void = () => {};
    const ask = current;
    relayGet.mockImplementation((path: string) => path === "/admin/proxies"
      ? Promise.resolve({ proxies: [], pool: { size: 0, account_ids: [] } })
      : new Promise<RemoteLoginStatus>((ok) => { stale = ok; }));
    void client.refetchQueries({ queryKey: ["remote-login", "job1"] }); // a poll in flight, read before the code
    fireEvent.change(field, { target: { value: "123456" } });
    relayPost.mockImplementation(() => Promise.resolve(job({ state: "otp", message: "checking the 2FA code", live_view_url: ask.live_view_url })));
    fireEvent.click(screen.getByRole("button", { name: "Submit code" }));
    expect(await screen.findByText("Checking the code with OnlyFans…")).toBeInTheDocument();
    await act(async () => { // the stale poll answers now; give react-query time to land it
      stale(ask);
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.getByText("Checking the code with OnlyFans…")).toBeInTheDocument();
    expect(screen.getByLabelText("2FA code")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Submit code" })).toBeDisabled();
  });

  it("keeps a newer poll that is already past the prompt when the POST answers later", async () => {
    current = job({ state: "otp", message: "OnlyFans asks for the 2FA code", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    start();
    const field = await screen.findByLabelText("2FA code");
    let answer: (j: RemoteLoginStatus) => void = () => {};
    relayPost.mockImplementation(() => new Promise<RemoteLoginStatus>((ok) => { answer = ok; }));
    fireEvent.change(field, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit code" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalled());
    current = job({ state: "typing", message: "waiting for OnlyFans", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    await act(async () => { await client.refetchQueries({ queryKey: ["remote-login", "job1"] }); }); // the code went in
    await waitFor(() => expect(screen.queryByLabelText("2FA code")).not.toBeInTheDocument());
    await act(async () => { // the POST's answer, read before the worker took the code, lands last
      answer(job({ state: "otp", message: "checking the 2FA code", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" }));
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.queryByLabelText("2FA code")).not.toBeInTheDocument();
    expect(client.getQueryData<RemoteLoginStatus>(["remote-login", "job1"])?.state).toBe("typing");
  });

  it("takes a pasted 1234-5678 as the 8-digit code, and leaves anything else visibly wrong", async () => {
    current = job({ state: "otp", message: "OnlyFans asks for the 2FA code", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    start();
    const field = await screen.findByLabelText("2FA code");
    const user = userEvent.setup();
    await user.click(field);
    await user.paste("1234-5678");
    expect(field).toHaveValue("12345678");
    const submit = screen.getByRole("button", { name: "Submit code" });
    expect(submit).toBeEnabled();
    await user.clear(field);
    await user.paste(" 123 456 ");
    expect(field).toHaveValue("123456");
    for (const typed of ["12a3456", "123456789", "123.456"]) {
      await user.clear(field);
      await user.type(field, typed);
      expect(field).toHaveValue(typed); // not turned into another code
      expect(submit).toBeDisabled();
    }
    await user.clear(field);
    await user.paste("1234-5678");
    relayPost.mockImplementation(() => Promise.resolve(job({ state: "otp", message: "checking the 2FA code" })));
    await user.click(submit);
    await waitFor(() => expect(relayPost).toHaveBeenLastCalledWith("/admin/login/remote/job1/otp", { code: "12345678" }));
  });

  it("says when the relay couldn't type the code", async () => {
    current = job({ state: "otp", message: "couldn't type the 2FA code — try again or type it in the live view", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    start();
    expect(await screen.findByRole("alert")).toHaveTextContent("The code couldn't be typed into OnlyFans. Try again, or type it in the live view.");
    expect(screen.getByLabelText("2FA code")).toBeEnabled();
  });

  it("clears the typed code and its error when the job leaves the 2FA prompt", async () => {
    current = job({ state: "otp", message: "OnlyFans asks for the 2FA code", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    start();
    const field = await screen.findByLabelText("2FA code");
    fireEvent.change(field, { target: { value: "654321" } });
    relayPost.mockImplementation(() => Promise.reject(new RelayError(409, {}, "a code is already being checked")));
    fireEvent.click(screen.getByRole("button", { name: "Submit code" }));
    expect(await screen.findByText("Couldn't send the code: a code is already being checked")).toBeInTheDocument();
    expect(screen.getByLabelText("2FA code")).toHaveValue("654321");
    current = job({ state: "typing", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    await act(async () => { client.setQueryData(["remote-login", "job1"], current); });
    await waitFor(() => expect(screen.queryByLabelText("2FA code")).toBeNull());
    current = job({ state: "otp", message: "OnlyFans asks for the 2FA code", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    await act(async () => { client.setQueryData(["remote-login", "job1"], current); });
    expect(await screen.findByLabelText("2FA code")).toHaveValue("");
    expect(screen.queryByText(/Couldn't send the code/)).toBeNull();
  });

  it("shows no code field outside the 2FA prompt", async () => {
    current = job({ state: "challenge", live_view_url: "https://www.browserbase.com/devtools-fullscreen/x" });
    start();
    await screen.findByText("OnlyFans is showing a verification check. Solve it in the live view.");
    expect(screen.queryByLabelText("2FA code")).toBeNull();
  });

  it("says a refused start couldn't start", async () => {
    relayPost.mockImplementation(() => Promise.reject(new RelayError(503, {}, "BROWSERBASE_API_KEY is not set")));
    start();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't start the login: BROWSERBASE_API_KEY is not set");
  });
});
