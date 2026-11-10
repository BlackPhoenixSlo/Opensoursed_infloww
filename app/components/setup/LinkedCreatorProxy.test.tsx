import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LinkedCreatorProxy from "./LinkedCreatorProxy";
import { BRAND_NAME } from "@/lib/brand";
import { relay } from "@/lib/relay";
vi.mock("@/lib/relay", async (original) => ({ ...await original<typeof import("@/lib/relay")>(), relay: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
const list = { proxies: [], pool: { size: 2, account_ids: ["creator/1"] } };
const busy = vi.fn();
beforeEach(() => { vi.clearAllMocks(); vi.mocked(relay.get).mockResolvedValue(list); vi.mocked(relay.post).mockResolvedValue({ ok: true }); vi.mocked(relay.delete).mockResolvedValue({}); });
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
it("hides the optional fields until expanded", () => { setup(); expect(screen.queryByLabelText("Port")).toBeNull(); });
it("tests the custom proxy before switching and reloading the linked account", async () => {
  setup(); await fill(); fireEvent.click(screen.getByRole("button", { name: "Connect proxy" }));
  await screen.findByText("Your proxy is connected.");
  expect(vi.mocked(relay.post).mock.calls.map(([path]) => path)).toEqual([
    "/admin/proxies", "/admin/proxies/proxy.example%3A8080/test", "/admin/proxy-pool/unbind", "/admin/proxies/assign", "/admin/reload-session?account_id=creator%2F1",
  ]);
  expect(relay.post).toHaveBeenCalledWith("/admin/proxies/assign", { label: "proxy.example:8080", account_id: "creator/1" });
  await waitFor(() => expect(busy).toHaveBeenLastCalledWith(false));
});
it("enables fallback by default and automatically connects it after a failed proxy test", async () => {
  vi.mocked(relay.post).mockImplementation(async (path) => path.endsWith('/test') ? { ok: false } : { ok: true });
  setup(); await fill();
  expect(screen.getByRole("checkbox", { name: `Use ${BRAND_NAME}'s default proxy if mine fails` })).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Connect proxy" }));
  await screen.findByText(`Your proxy could not connect. This creator is now using ${BRAND_NAME}'s default proxy.`);
  expect(relay.delete).toHaveBeenCalledWith("/admin/proxies/proxy.example%3A8080");
  expect(relay.post).not.toHaveBeenCalledWith("/admin/proxy-pool/unbind", expect.anything());
  expect(relay.post).toHaveBeenCalledWith("/admin/proxy-pool/assign", { account_id: "creator/1" });
  expect(relay.post).toHaveBeenCalledWith("/admin/reload-session?account_id=creator%2F1");
});
it("leaves a failed custom test as an error when fallback is unchecked", async () => {
  vi.mocked(relay.post).mockResolvedValue({ ok: false });
  setup(); await fill();
  fireEvent.click(screen.getByRole("checkbox", { name: `Use ${BRAND_NAME}'s default proxy if mine fails` }));
  fireEvent.click(screen.getByRole("button", { name: "Connect proxy" }));
  await screen.findByRole("alert");
  expect(relay.post).not.toHaveBeenCalledWith("/admin/proxy-pool/assign", expect.anything());
  expect(relay.post).not.toHaveBeenCalledWith("/admin/proxy-pool/unbind", expect.anything());
});
it("rejects a duplicate found on the fresh read before overwriting it", async () => {
  setup(); await fill();
  vi.mocked(relay.get).mockResolvedValue({ ...list, proxies: [{ label: "proxy.example:8080" }] });
  fireEvent.click(screen.getByRole("button", { name: "Connect proxy" }));
  await screen.findByRole("alert"); expect(relay.post).not.toHaveBeenCalled();
});
it("recovers from a failed custom reload by assigning and reloading the default", async () => {
  let reloads = 0;
  vi.mocked(relay.post).mockImplementation(async (path) => {
    if (path.startsWith('/admin/reload-session') && ++reloads === 1) throw new Error('custom reload failed');
    return { ok: true };
  });
  setup(); await fill(); fireEvent.click(screen.getByRole("button", { name: "Connect proxy" }));
  await screen.findByText(`Your proxy could not connect. This creator is now using ${BRAND_NAME}'s default proxy.`);
  expect(reloads).toBe(2);
  expect(relay.post).toHaveBeenCalledWith("/admin/proxy-pool/assign", { account_id: "creator/1" });
});
it("shows an error if the default fallback also fails", async () => {
  vi.mocked(relay.post).mockImplementation(async (path) => {
    if (path === '/admin/proxy-pool/assign') throw new Error('pool unavailable');
    return { ok: false };
  });
  setup(); await fill(); fireEvent.click(screen.getByRole("button", { name: "Connect proxy" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't connect the proxy or the default proxy");
  expect(screen.queryByRole("status")).toBeNull();
});
