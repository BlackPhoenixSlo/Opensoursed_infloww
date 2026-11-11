import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LinkedCreatorProxy from "./LinkedCreatorProxy";
import { BRAND_NAME } from "@/lib/brand";
import { relay } from "@/lib/relay";
vi.mock("@/lib/relay", async (original) => ({ ...await original<typeof import("@/lib/relay")>(), relay: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
const ON_POOL = { proxies: [], pool: { size: 2, account_ids: ["creator/1"] } };
const ON_CUSTOM = { proxies: [{ label: "old", assigned_account_ids: ["creator/1"] }], pool: { size: 2, account_ids: [] } };
const ON_NONE = { proxies: [], pool: { size: 2, account_ids: [] } };
const busy = vi.fn();
const posts = () => vi.mocked(relay.post).mock.calls.map(([path]) => path);
beforeEach(() => { vi.clearAllMocks(); vi.mocked(relay.get).mockResolvedValue(ON_POOL); vi.mocked(relay.post).mockResolvedValue({ ok: true }); vi.mocked(relay.delete).mockResolvedValue({}); });
afterEach(cleanup);
function setup() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><LinkedCreatorProxy accountId="creator/1" onBusy={busy} /></QueryClientProvider>);
}
async function fill() {
  fireEvent.click(screen.getByRole("button", { name: "Click here to add your proxy" }));
  fireEvent.change(screen.getByLabelText("IP address or hostname"), { target: { value: "proxy.example" } });
  fireEvent.change(screen.getByLabelText("Port"), { target: { value: "8080" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Connect proxy" })).toBeEnabled());
}
const connect = () => fireEvent.click(screen.getByRole("button", { name: "Connect proxy" }));
const failTest = (error = "timed out") => vi.mocked(relay.post).mockImplementation(async (path) => path.endsWith("/test") ? { ok: false, error } : { ok: true });

it("hides the optional fields until expanded", () => { setup(); expect(screen.queryByLabelText("Port")).toBeNull(); });

it("create → test → assign → reload, never unbinding first", async () => {
  setup(); await fill(); connect();
  await screen.findByText("Your proxy is connected.");
  expect(posts()).toEqual([
    "/admin/proxies", "/admin/proxies/proxy.example%3A8080/test", "/admin/proxies/assign", "/admin/reload-session?account_id=creator%2F1",
  ]);
  expect(relay.post).toHaveBeenCalledWith("/admin/proxies/assign", { label: "proxy.example:8080", account_id: "creator/1" });
  await waitFor(() => expect(busy).toHaveBeenLastCalledWith(false));
});

it("fallback on: a failed test deletes the candidate and keeps the creator on its custom proxy (no pool write)", async () => {
  vi.mocked(relay.get).mockResolvedValue(ON_CUSTOM);
  failTest();
  setup(); await fill();
  expect(screen.getByRole("checkbox", { name: "If my proxy fails its test, keep this creator on its current proxy (old)" })).toBeChecked();
  connect();
  await screen.findByText("Your proxy failed its test (timed out). This creator stays on its current proxy (old).");
  expect(relay.delete).toHaveBeenCalledWith("/admin/proxies/proxy.example%3A8080");
  expect(posts()).toEqual(["/admin/proxies", "/admin/proxies/proxy.example%3A8080/test"]);
  expect(screen.queryByLabelText("Port")).toBeNull(); // folded
});

it("fallback on: an account on no proxy goes on the default pool when its test fails", async () => {
  vi.mocked(relay.get).mockResolvedValue(ON_NONE);
  failTest();
  setup(); await fill();
  expect(screen.getByRole("checkbox", { name: `If my proxy fails its test, keep this creator on ${BRAND_NAME}'s default proxy` })).toBeChecked();
  connect();
  await screen.findByText(`Your proxy failed its test (timed out). This creator stays on ${BRAND_NAME}'s default proxy.`);
  expect(posts()).toEqual([
    "/admin/proxies", "/admin/proxies/proxy.example%3A8080/test", "/admin/proxy-pool/assign", "/admin/reload-session?account_id=creator%2F1",
  ]);
});

it("fallback to the pool: bound but the reload fails → says it is on the pool, Retry reloads only, then the pool line", async () => {
  vi.mocked(relay.get).mockResolvedValue(ON_NONE);
  let reloads = 0;
  vi.mocked(relay.post).mockImplementation(async (path) => {
    if (path.endsWith("/test")) return { ok: false, error: "timed out" };
    if (path.startsWith("/admin/reload-session") && ++reloads === 1) throw new Error("relay 502");
    return { ok: true };
  });
  setup(); await fill(); connect();
  await screen.findByText(
    `Your proxy failed its test (timed out). This creator is now on ${BRAND_NAME}'s default proxy, but the session refresh failed (relay 502). Retry the refresh.`);
  expect(screen.queryByText(/couldn't be attached/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Retry session refresh" }));
  await screen.findByText(`Your proxy failed its test (timed out). This creator stays on ${BRAND_NAME}'s default proxy.`);
  expect(posts().filter((p) => p === "/admin/proxy-pool/assign")).toHaveLength(1);
  expect(posts().slice(-1)).toEqual(["/admin/reload-session?account_id=creator%2F1"]);
});

it("fallback to the pool: a failed bind says the default proxy couldn't be attached, and reloads nothing", async () => {
  vi.mocked(relay.get).mockResolvedValue(ON_NONE);
  vi.mocked(relay.post).mockImplementation(async (path) => {
    if (path.endsWith("/test")) return { ok: false, error: "timed out" };
    if (path === "/admin/proxy-pool/assign") throw new Error("pool 500");
    return { ok: true };
  });
  setup(); await fill(); connect();
  expect(await screen.findByRole("alert")).toHaveTextContent("The default proxy couldn't be attached either: pool 500");
  expect(posts()).not.toContain("/admin/reload-session?account_id=creator%2F1");
  expect(screen.queryByRole("button", { name: "Retry session refresh" })).toBeNull();
});

it("fallback off: a failed test leaves the form open with the relay's error, nothing else written", async () => {
  failTest("403 from OnlyFans");
  setup(); await fill();
  fireEvent.click(screen.getByRole("checkbox"));
  connect();
  expect(await screen.findByRole("alert")).toHaveTextContent("Your proxy failed its test (403 from OnlyFans). Check its details and try again.");
  expect(posts()).toEqual(["/admin/proxies", "/admin/proxies/proxy.example%3A8080/test"]);
  expect(relay.delete).toHaveBeenCalledWith("/admin/proxies/proxy.example%3A8080");
  expect(screen.getByLabelText("Port")).toHaveValue("8080");
});

it("the copy follows the box as it was at Connect, not as it is after", async () => {
  let pass: (v: unknown) => void = () => {};
  vi.mocked(relay.post).mockImplementation((path) => path.endsWith("/test") ? new Promise((r) => { pass = r; }) : Promise.resolve({ ok: true }));
  setup(); await fill(); connect();
  await waitFor(() => expect(posts()).toContain("/admin/proxies/proxy.example%3A8080/test"));
  fireEvent.click(screen.getByRole("checkbox")); // disabled while checking: the box stays as submitted
  pass({ ok: false, error: "x" });
  await screen.findByText(/This creator stays on/);
});

it("a duplicate on the fresh read shows its own error and creates nothing", async () => {
  setup(); await fill();
  vi.mocked(relay.get).mockResolvedValue({ ...ON_POOL, proxies: [{ label: "proxy.example:8080" }] });
  connect();
  expect(await screen.findByRole("alert")).toHaveTextContent('A proxy named "proxy.example:8080" already exists');
  expect(relay.post).not.toHaveBeenCalled();
});

it("a failed create shows the relay's error and leaves the binding alone", async () => {
  vi.mocked(relay.post).mockImplementation(async (path) => { if (path === "/admin/proxies") throw new Error("port refused"); return { ok: true }; });
  setup(); await fill(); connect();
  expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't add your proxy: port refused");
  expect(posts()).toEqual(["/admin/proxies"]);
});

it("a failed assign: binding unchanged, the unassigned candidate deleted, the error shown (no pool fallback)", async () => {
  vi.mocked(relay.post).mockImplementation(async (path) => { if (path === "/admin/proxies/assign") throw new Error("assign 500"); return { ok: true }; });
  setup(); await fill();
  vi.mocked(relay.get).mockResolvedValueOnce(ON_POOL).mockResolvedValue({ ...ON_POOL, proxies: [{ label: "proxy.example:8080", assigned_account_ids: [] }] });
  connect();
  expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't assign your proxy: assign 500. This creator's proxy is unchanged.");
  expect(relay.delete).toHaveBeenCalledWith("/admin/proxies/proxy.example%3A8080");
  expect(posts()).not.toContain("/admin/proxy-pool/assign");
});

it("an assign error whose fresh read shows the proxy on this account counts as assigned: reload, connected", async () => {
  vi.mocked(relay.post).mockImplementation(async (path) => { if (path === "/admin/proxies/assign") throw new Error("timeout"); return { ok: true }; });
  setup(); await fill();
  vi.mocked(relay.get).mockResolvedValueOnce(ON_POOL).mockResolvedValue({ ...ON_POOL, proxies: [{ label: "proxy.example:8080", assigned_account_ids: ["creator/1"] }] });
  connect();
  await screen.findByText("Your proxy is connected.");
  expect(posts().slice(-1)).toEqual(["/admin/reload-session?account_id=creator%2F1"]);
  expect(relay.delete).not.toHaveBeenCalled();
});

it("a failed assign never deletes a candidate the fresh read shows on another account", async () => {
  vi.mocked(relay.post).mockImplementation(async (path) => { if (path === "/admin/proxies/assign") throw new Error("timeout"); return { ok: true }; });
  setup(); await fill();
  vi.mocked(relay.get).mockResolvedValueOnce(ON_POOL).mockResolvedValue({ ...ON_POOL, proxies: [{ label: "proxy.example:8080", assigned_account_ids: ["creator/2"] }] });
  connect();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Couldn't assign your proxy: timeout. This creator's proxy is unchanged. The new proxy proxy.example:8080 shows as in use by another account, so it was kept.");
  expect(relay.delete).not.toHaveBeenCalled();
  expect(posts()).not.toContain("/admin/reload-session?account_id=creator%2F1");
});

it("a failed reload keeps the new binding and retries the reload only", async () => {
  let reloads = 0;
  vi.mocked(relay.post).mockImplementation(async (path) => {
    if (path.startsWith("/admin/reload-session") && ++reloads === 1) throw new Error("relay 502");
    return { ok: true };
  });
  setup(); await fill(); connect();
  await screen.findByText("Proxy proxy.example:8080 is assigned, but the session refresh failed (relay 502). Retry the refresh.");
  expect(relay.delete).not.toHaveBeenCalled();
  expect(posts()).not.toContain("/admin/proxy-pool/assign");
  fireEvent.click(screen.getByRole("button", { name: "Retry session refresh" }));
  await screen.findByText("Your proxy is connected.");
  expect(posts().slice(-1)).toEqual(["/admin/reload-session?account_id=creator%2F1"]);
  expect(posts().filter((p) => p === "/admin/proxies/assign")).toHaveLength(1);
});

it("a failed assign whose re-read fails deletes nothing and claims nothing about the binding", async () => {
  vi.mocked(relay.post).mockImplementation(async (path) => { if (path === "/admin/proxies/assign") throw new Error("assign 500"); return { ok: true }; });
  setup(); await fill();
  vi.mocked(relay.get).mockResolvedValueOnce(ON_POOL).mockRejectedValue(new Error("read 502"));
  connect();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Couldn't assign your proxy: assign 500. Couldn't re-read the proxies (read 502), so it is unknown whether this creator is on proxy.example:8080; check it under Custom proxy.");
  expect(screen.getByRole("alert")).not.toHaveTextContent("unchanged");
  expect(relay.delete).not.toHaveBeenCalled();
});
