/**
 * VaultDuplicatesModal through the real component + react-query: a threshold
 * change while confirming must take "Yes, remove them" away (the frozen set
 * belonged to the old scan), the hide request must carry exactly the ids
 * frozen at confirm (even when a refetch changed the scan underneath), a failed
 * hide is never resent, and a double click sends once. Only the relay wire is faked.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), post: vi.fn() } };
});

import VaultDuplicatesModal from "@/components/vault/VaultDuplicatesModal";
import type { DupeCluster, DupeMember } from "@/hooks/useVaultCache";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const ACCT = "123456789";

const member = (media_id: number): DupeMember => ({
  media_id, kind: "photo", created_at: "2026-01-01T00:00:00Z", duration_seconds: null,
  send_count: 0, exact: true, band: "identical",
});
const cluster = (original: number, dupes: number[]): DupeCluster => ({
  original: member(original), dupes: dupes.map(member), band: "identical", worst: 0,
  all_exact: true, sent_dupes: 0,
});
/** Threshold 2 finds two sets; the looser threshold 4 finds a third. */
const SCANS: Record<string, DupeCluster[]> = {
  "2": [cluster(1, [11, 12]), cluster(2, [21])],
  "4": [cluster(1, [11, 12]), cluster(2, [21]), cluster(3, [31])],
};

type HideBody = { media_ids: number[] };
const hideOk = async (body: HideBody) => ({
  hidden: body.media_ids.length, hidden_ids: body.media_ids, refused: {},
});

function serve(scans: Record<string, DupeCluster[]> = SCANS, hide = hideOk) {
  relayGet.mockImplementation(async (path: string) => {
    if (path.startsWith("/admin/vault-ai/duplicates?")) {
      const t = new URLSearchParams(path.split("?")[1]).get("threshold") ?? "2";
      const clusters = scans[t] ?? [];
      const removable = clusters.reduce((n, c) => n + c.dupes.length, 0);
      return {
        account_id: ACCT, threshold: Number(t), scanned: 50, unhashed: 0,
        sets: clusters.length, removable, returned: clusters.length, clusters,
      };
    }
    throw new Error(`unexpected GET ${path}`);
  });
  relayPost.mockImplementation(async (path: string, body: HideBody) => {
    if (path === "/admin/vault-ai/duplicates/hide") return hide(body);
    throw new Error(`unexpected POST ${path}`);
  });
}

function mount(onClose = () => {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <VaultDuplicatesModal accountId={ACCT} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { qc };
}

const scanCalls = () =>
  relayGet.mock.calls.filter(([p]) => String(p).startsWith("/admin/vault-ai/duplicates?"));
const hideCalls = () => relayPost.mock.calls.filter(([p]) => p === "/admin/vault-ai/duplicates/hide");
const tile = (id: number) => screen.getByAltText(`media ${id}`).closest("button") as HTMLButtonElement;

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("VaultDuplicatesModal confirm over a threshold change", () => {
  it("a threshold change drops the pending confirm; the hide sends exactly the frozen ids", async () => {
    serve();
    mount();
    await screen.findByText("Remove 3 copies from OnlyFans…");

    // Select: untick #21, leaving 11 + 12, and ask to remove them.
    fireEvent.click(tile(21));
    fireEvent.click(screen.getByText("Remove 2 copies from OnlyFans…"));
    expect(screen.getByText("Yes, remove them")).toBeTruthy();

    // A new scan while confirming: the confirm row goes, nothing is sent.
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "4" } });
    expect(screen.queryByText("Yes, remove them")).toBeNull();
    expect(hideCalls()).toHaveLength(0);

    // The new scan lands with every copy ticked again (unticked set reset).
    await screen.findByText("Remove 4 copies from OnlyFans…");
    expect(hideCalls()).toHaveLength(0);

    // Confirm the scan on screen, then Yes: the request carries the frozen set.
    fireEvent.click(screen.getByText("Remove 4 copies from OnlyFans…"));
    fireEvent.click(screen.getByText("Yes, remove them"));
    await screen.findByText(/Removed 4/);
    expect(hideCalls()).toHaveLength(1);
    const [, body] = hideCalls()[0];
    expect(body).toMatchObject({ account_id: ACCT, media_ids: [11, 12, 21, 31], threshold: 4 });
    await waitFor(() => expect(screen.queryByText("Yes, remove them")).toBeNull());
  });
});

describe("VaultDuplicatesModal hide request", () => {
  it("a scan refetch while confirming leaves the frozen ids: Yes sends those, not the new selection", async () => {
    const scans = { ...SCANS };
    serve(scans);
    const { qc } = mount();
    fireEvent.click(await screen.findByText("Remove 3 copies from OnlyFans…"));
    expect(screen.getByText(/^Removes 3 from your real vault/)).toBeTruthy();

    // Same threshold, the scan now finds a third set: the live selection grows to 4.
    scans["2"] = SCANS["4"];
    await qc.invalidateQueries({ queryKey: ["vault-duplicates"] });
    await screen.findByText("4 selected for removal");
    expect(screen.getByText(/^Removes 3 from your real vault/)).toBeTruthy();

    fireEvent.click(screen.getByText("Yes, remove them"));
    await screen.findByText(/Removed 3/);
    expect(hideCalls()).toHaveLength(1);
    expect(hideCalls()[0][1]).toMatchObject({ media_ids: [11, 12, 21], threshold: 2 });
  });

  it("a failed hide shows the error, reports nothing removed, refreshes the scan, and is not resent", async () => {
    serve(SCANS, async () => { throw new Error("relay 502"); });
    mount();
    fireEvent.click(await screen.findByText("Remove 3 copies from OnlyFans…"));
    const scansBefore = scanCalls().length;
    fireEvent.click(screen.getByText("Yes, remove them"));
    await screen.findByText("relay 502");
    expect(screen.queryByText(/Removed/)).toBeNull();
    expect(screen.queryByText("Yes, remove them")).toBeNull();
    await waitFor(() => expect(scanCalls().length).toBeGreaterThan(scansBefore));
    expect(hideCalls()).toHaveLength(1);
  });

  it("while the hide is out: a double click sends once, and neither × nor Escape can close it", async () => {
    let release: (v: unknown) => void = () => {};
    serve(SCANS, (body) => new Promise((res) => { release = () => res(hideOk(body)); }));
    const onClose = vi.fn();
    mount(onClose);
    fireEvent.click(await screen.findByText("Remove 3 copies from OnlyFans…"));
    const yes = screen.getByText("Yes, remove them");
    fireEvent.click(yes);
    fireEvent.click(yes);
    await screen.findByText("Removing 0/3…");
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    release(undefined);
    await screen.findByText(/Removed 3/);
    expect(hideCalls()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

});

describe("the state-reducers slop scenario's selectors match this modal", () => {
  // Its page.evaluate reading the ticked copies, run here on the same DOM.
  const scenario = readFileSync(resolve(__dirname, "../../../slop/scenarios/2026-10-29-state-reducers.py"), "utf8");
  const js = /TICKED_DUPES = """([\s\S]*?)"""/.exec(scenario)![1];
  const ticked = new Function(`return (${js})();`) as () => number[];

  it("TICKED_DUPES reads the ticked copies (aria-pressed), and the dialog by name has its Close", async () => {
    serve();
    mount();
    await screen.findByText("Remove 3 copies from OnlyFans…");
    expect(ticked()).toEqual([11, 12, 21]);
    expect(tile(11)).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(tile(21));
    expect(tile(21)).toHaveAttribute("aria-pressed", "false");
    expect(ticked()).toEqual([11, 12]);
    // page.get_by_role("dialog", name="Duplicate media").get_by_role("button", name="Close")
    within(screen.getByRole("dialog", { name: "Duplicate media" })).getByRole("button", { name: "Close" });
  });
});
