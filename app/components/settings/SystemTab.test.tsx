/**
 * Settings → System is the master's alone: anyone else gets the 404 page (notFound), never the Panel,
 * and nothing is fetched for them; the master gets the Panel. Its Runtime switches section lists every
 * switch with its source and effective value, sets an override (a toggle for on/off, a number and Set for
 * a cap) and clears it, each one PUT /admin/system/switches/{env} carrying the admin password. Landing
 * back on the env / default value clears instead of storing; an override that beats a set env var is
 * badged; a relay that could not read its overrides shows a banner.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";

const notFound = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});
vi.mock("next/navigation", () => ({ notFound: () => notFound() }));
let session: { user: { username: string; is_admin?: boolean } | null; loading: boolean };
vi.mock("@/contexts/UserContext", () => ({ useUser: () => session }));

const sw = <T extends Record<string, unknown>>(over: T) => ({
  label: "x", effect: "does x", minimum: null, maximum: null, env_raw: null, env_value: null, override: null,
  override_at: null, override_by: null, source: "default", active: false, overrides_env: false, ...over,
});
const W7 = sw({ env: "W7_WEBHOOK_DISPATCH_DISABLED", label: "Instant DM dispatch off", kind: "bool",
                default: false, fallback: false, effective: false });
const CAP = sw({ env: "SMART_LIST_MAX_ACTIVE", label: "Active smart lists per Creator", kind: "number",
                 default: 10, fallback: 10, effective: 4, minimum: 1, maximum: 50, source: "override",
                 override: 4, override_by: "master", active: true });
const ENV = sw({ env: "STYLE_FORCE_OFF", kind: "bool", default: false, fallback: true, effective: true,
                 env_raw: "1", env_value: true, source: "env", active: true });
const ALL = [W7, CAP, ENV];
let loaded = true;

const get = vi.fn((path: string) =>
  Promise.resolve(path.startsWith("/admin/system/automations")
    ? { accounts: [], mismatch_count: 0 }
    : path.startsWith("/admin/system/switches") ? { switches: ALL, loaded }
    : path.startsWith("/admin/system/runs") ? { runs: [], jobs: [] } : { keys: {} }),
);
type Body = { value: unknown; admin_password?: string };
/** The relay's answer: null clears back to the fallback; a value becomes the override. */
const put = vi.fn((path: string, body: Body) => {
  const base = ALL.find((k) => k.env === path.split("/").pop())!;
  const fromEnv = base.env_raw !== null;
  return Promise.resolve({ switch: body.value === null
    ? { ...base, source: fromEnv ? "env" : "default", override: null, effective: base.fallback,
        active: base.fallback !== base.default, overrides_env: false }
    : { ...base, source: "override", override: body.value, effective: body.value,
        active: body.value !== base.default, overrides_env: fromEnv && body.value !== base.env_value } });
});
vi.mock("@/lib/relay", () => ({
  relay: { get: (p: string) => get(p), put: (p: string, b: Body) => put(p, b) },
}));
vi.mock("@/components/setup/KeysCard", () => ({ default: () => <p>house keys</p> }));
vi.mock("@/components/setup/ManagedAgencyKeysCard", () => ({ default: () => <p>agency keys</p> }));

import SystemTab from "@/components/settings/SystemTab";

beforeEach(() => {
  notFound.mockClear();
  get.mockClear();
  put.mockClear();
  loaded = true;
});

const master = (password: string | null = "pw") => {
  session = { user: { username: "master", is_admin: true }, loading: false };
  renderWithProviders(<SystemTab />);
  if (password) fireEvent.change(screen.getByLabelText("Admin password"), { target: { value: password } });
};
const row = async (env: string) => screen.findByTestId(`switch-${env}`);
const URL = (env: string) => `/admin/system/switches/${env}`;

describe("SystemTab", () => {
  it("404s an owner and fetches nothing", () => {
    session = { user: { username: "owner", is_admin: false }, loading: false };
    expect(() => renderWithProviders(<SystemTab />)).toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalled();
    expect(get).not.toHaveBeenCalled();
  });

  it("404s a session with no user (a chatter)", () => {
    session = { user: null, loading: false };
    expect(() => renderWithProviders(<SystemTab />)).toThrow("NEXT_NOT_FOUND");
  });

  it("draws nothing while the session loads", () => {
    session = { user: null, loading: true };
    renderWithProviders(<SystemTab />);
    expect(notFound).not.toHaveBeenCalled();
    expect(screen.queryByText("System")).toBeNull();
  });

  it("shows the master the keys, switches, automations and run log", async () => {
    master();
    expect(screen.getByRole("heading", { name: "System" })).toBeInTheDocument();
    expect(screen.getByText("house keys")).toBeInTheDocument();
    expect(screen.getByText("Runtime switches")).toBeInTheDocument();
    expect(screen.getByText("Automations on / off")).toBeInTheDocument();
    expect(await screen.findByText("No runs match.")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/admin/system/automations");
    expect(get).toHaveBeenCalledWith("/admin/system/switches");
    expect(screen.queryByText(/could not read its saved overrides/)).toBeNull();
  });

  it("shows each switch's source and effective value", async () => {
    master();
    const w7 = within(await row("W7_WEBHOOK_DISPATCH_DISABLED"));
    expect(w7.getByTestId("switch-source")).toHaveTextContent("default");
    expect(w7.getByTestId("switch-effective")).toHaveTextContent("off");
    expect(w7.getByRole("button", { name: "Clear override" })).toBeDisabled();
    const cap = within(await row("SMART_LIST_MAX_ACTIVE"));
    expect(cap.getByTestId("switch-source")).toHaveTextContent("override by master");
    expect(cap.getByTestId("switch-effective")).toHaveTextContent("4 (ACTIVE)");
    const env = within(await row("STYLE_FORCE_OFF"));
    expect(env.getByTestId("switch-source")).toHaveTextContent("env 1");
    expect(env.getByRole("switch", { name: "STYLE_FORCE_OFF" })).toHaveAttribute("aria-checked", "true");
  });

  it("a toggle sets the override with the password, and toggling back clears it", async () => {
    master();
    const w7 = within(await row("W7_WEBHOOK_DISPATCH_DISABLED"));
    const toggle = w7.getByRole("switch", { name: "W7_WEBHOOK_DISPATCH_DISABLED" });
    fireEvent.click(toggle);
    await waitFor(() => expect(w7.getByTestId("switch-source")).toHaveTextContent("override"));
    expect(put).toHaveBeenCalledWith(URL("W7_WEBHOOK_DISPATCH_DISABLED"), { value: true, admin_password: "pw" });
    expect(w7.getByTestId("switch-effective")).toHaveTextContent("on (ACTIVE)");
    expect(w7.getByRole("button", { name: "Clear override" })).toBeEnabled();
    // Back to the default: a clear (null), never a stored `false` that would outrank a later env change.
    fireEvent.click(toggle);
    await waitFor(() => expect(w7.getByTestId("switch-source")).toHaveTextContent("default"));
    expect(put).toHaveBeenLastCalledWith(URL("W7_WEBHOOK_DISPATCH_DISABLED"), { value: null, admin_password: "pw" });
  });

  it("an override against a set env var is badged", async () => {
    master();
    const env = within(await row("STYLE_FORCE_OFF"));
    fireEvent.click(env.getByRole("switch", { name: "STYLE_FORCE_OFF" }));
    await waitFor(() => expect(env.getByTestId("switch-source")).toHaveTextContent("beats env 1"));
    expect(put).toHaveBeenCalledWith(URL("STYLE_FORCE_OFF"), { value: false, admin_password: "pw" });
  });

  it("no change is sent without the admin password", async () => {
    master(null);
    const w7 = within(await row("W7_WEBHOOK_DISPATCH_DISABLED"));
    fireEvent.click(w7.getByRole("switch", { name: "W7_WEBHOOK_DISPATCH_DISABLED" }));
    expect(await screen.findByText(/Admin password required/)).toBeInTheDocument();
    expect(put).not.toHaveBeenCalled();
  });

  it("a number is set with Set, refused outside its range, and Clear override sends null", async () => {
    master();
    const cap = within(await row("SMART_LIST_MAX_ACTIVE"));
    const box = cap.getByRole("spinbutton", { name: "SMART_LIST_MAX_ACTIVE" });
    for (const bad of ["0", "51", "2.5", ""]) {
      fireEvent.change(box, { target: { value: bad } });
      expect(cap.getByRole("button", { name: "Set" })).toBeDisabled();
    }
    fireEvent.change(box, { target: { value: "7" } });
    fireEvent.click(cap.getByRole("button", { name: "Set" }));
    await waitFor(() => expect(cap.getByTestId("switch-effective")).toHaveTextContent("7"));
    expect(put).toHaveBeenCalledWith(URL("SMART_LIST_MAX_ACTIVE"), { value: 7, admin_password: "pw" });
    fireEvent.click(cap.getByRole("button", { name: "Clear override" }));
    await waitFor(() => expect(cap.getByTestId("switch-source")).toHaveTextContent("default"));
    expect(put).toHaveBeenLastCalledWith(URL("SMART_LIST_MAX_ACTIVE"), { value: null, admin_password: "pw" });
    expect(cap.getByTestId("switch-effective")).toHaveTextContent("10");
  });

  it("banners a relay that could not read its saved overrides", async () => {
    loaded = false;
    master();
    expect(await screen.findByText(/could not read its saved overrides/)).toBeInTheDocument();
  });
});
