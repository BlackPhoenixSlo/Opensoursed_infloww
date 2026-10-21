/**
 * Settings → System is the master's alone: anyone else gets the 404 page (notFound), never the Panel,
 * and nothing is fetched for them; the master gets the Panel.
 */
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";

const notFound = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});
vi.mock("next/navigation", () => ({ notFound: () => notFound() }));
let session: { user: { username: string; is_admin?: boolean } | null; loading: boolean };
vi.mock("@/contexts/UserContext", () => ({ useUser: () => session }));
const get = vi.fn((path: string) =>
  Promise.resolve(path.startsWith("/admin/system/automations")
    ? { accounts: [], kill_switches: [], mismatch_count: 0 }
    : path.startsWith("/admin/system/runs") ? { runs: [], jobs: [] } : { keys: {} }),
);
vi.mock("@/lib/relay", () => ({ relay: { get: (p: string) => get(p), put: vi.fn() } }));
vi.mock("@/components/setup/KeysCard", () => ({ default: () => <p>house keys</p> }));
vi.mock("@/components/setup/ManagedAgencyKeysCard", () => ({ default: () => <p>agency keys</p> }));

import SystemTab from "@/components/settings/SystemTab";

beforeEach(() => {
  notFound.mockClear();
  get.mockClear();
});

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

  it("shows the master the keys, automations and run log", async () => {
    session = { user: { username: "master", is_admin: true }, loading: false };
    renderWithProviders(<SystemTab />);
    expect(screen.getByRole("heading", { name: "System" })).toBeInTheDocument();
    expect(screen.getByText("house keys")).toBeInTheDocument();
    expect(screen.getByText("Automations on / off")).toBeInTheDocument();
    expect(await screen.findByText("No runs match.")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/admin/system/automations");
  });
});
