/**
 * PriorityMassComposer's MASSDMEXCLUDE seed: the Creator's OF list named
 * MASSDMEXCLUDE is pre-ticked in Exclude once its lists land (as Mass and the
 * funnel launch do), Send waits for that seed, and an untick sticks. Relay
 * mocked; the composer's pickers stubbed (not this file's subject).
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), post: vi.fn() } };
});
vi.mock("@/components/compose/AccountPicker", () => ({ AccountPicker: () => null }));
vi.mock("@/components/compose/MediaTray", () => ({ MediaTray: () => null }));
vi.mock("@/components/chat/VaultPicker", () => ({ VaultPicker: () => null }));
vi.mock("@/lib/sensitiveWords", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/sensitiveWords")>()),
  useSensitiveHits: () => [],
}));

import { relay } from "@/lib/relay";
import { PriorityMassComposer } from "./PriorityMass";

const ACCOUNT = "111";
const VIP = { id: 501, name: "VIP", type: "custom", usersCount: 3 };
const MASSDM = { id: 502, name: "MASSDMEXCLUDE", type: "custom", usersCount: 2 };

let lists: Promise<unknown>;

beforeEach(() => {
  lists = Promise.resolve({ list: [VIP, MASSDM], hasMore: false });
  (relay.get as Mock).mockImplementation((path: string) =>
    path.startsWith("/api/of/v2/lists") ? lists : Promise.reject(new Error(`unexpected GET ${path}`)));
  (relay.post as Mock).mockResolvedValue({ id: 1 });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <PriorityMassComposer open onClose={() => {}} initialAccountId={ACCOUNT} />
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "hey {name}" } });
}

/** The list's checkbox in Include (0) or Exclude (1). */
const box = (name: string, side: 0 | 1) =>
  screen.getAllByRole("checkbox", { name: new RegExp(`^${name}`) })[side] as HTMLInputElement;
const send = () => screen.getByRole("button", { name: "Send" });

async function sentBody(): Promise<Record<string, unknown>> {
  await waitFor(() => expect(send()).toBeEnabled());
  fireEvent.click(send());
  await waitFor(() => expect(relay.post).toHaveBeenCalledTimes(1));
  return (relay.post as Mock).mock.calls[0][1];
}

describe("PriorityMassComposer MASSDMEXCLUDE seed", () => {
  it("pre-ticks the OF list named MASSDMEXCLUDE in Exclude and sends its id", async () => {
    mount();
    await waitFor(() => expect(box("MASSDMEXCLUDE", 1)).toBeChecked());
    expect(box("MASSDMEXCLUDE", 0)).not.toBeChecked();
    const body = await sentBody();
    expect(body.excluded_user_lists).toEqual(["502"]);
    expect(body.user_lists).toEqual(["fans", "following"]);
  });

  it("no such list: seeded, nothing excluded", async () => {
    lists = Promise.resolve({ list: [VIP], hasMore: false });
    mount();
    await waitFor(() => expect(box("VIP", 1)).toBeInTheDocument());
    expect(box("VIP", 1)).not.toBeChecked();
    const body = await sentBody();
    expect(body.excluded_user_lists).toEqual([]);
  });

  it("Send is disabled while the lists fetch", async () => {
    let land!: (v: unknown) => void;
    lists = new Promise((r) => { land = r; });
    mount();
    expect(send()).toBeDisabled();
    expect(send()).toHaveAttribute("title", "Loading the Creator's lists…");
    fireEvent.click(send());
    expect(relay.post).not.toHaveBeenCalled();
    land({ list: [VIP, MASSDM], hasMore: false });
    await waitFor(() => expect(send()).toBeEnabled());
    expect(box("MASSDMEXCLUDE", 1)).toBeChecked();
  });

  it("lists read fails: Send stays disabled and says so", async () => {
    lists = Promise.reject(new Error("OF 502"));
    mount();
    await waitFor(() => expect(send()).toHaveAttribute("title", "Couldn't load the Creator's lists — reopen to retry"));
    expect(send()).toBeDisabled();
    fireEvent.click(send());
    expect(relay.post).not.toHaveBeenCalled();
  });

  it("an untick sticks: the body goes without it", async () => {
    mount();
    await waitFor(() => expect(box("MASSDMEXCLUDE", 1)).toBeChecked());
    fireEvent.click(box("MASSDMEXCLUDE", 1));
    expect(box("MASSDMEXCLUDE", 1)).not.toBeChecked();
    const body = await sentBody();
    expect(body.excluded_user_lists).toEqual([]);
  });
});
