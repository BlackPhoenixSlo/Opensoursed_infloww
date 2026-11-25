import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { ReactNode } from "react";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/relay")>()),
  relay: { get: vi.fn(), post: vi.fn() },
}));

import {
  describeSweepText,
  sweepAbortedNote,
  harvestSweepLabel,
  sweepCounts,
  sweepStatusKey,
  useVaultSweep,
  type SweepStatus,
} from "@/hooks/useVaultSweep";
import { ApiKeyError, relay, RelayError } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const AID = "506355167";

let server: SweepStatus;

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  server = { running: false, progress: null };
  relayGet.mockReset();
  relayPost.mockReset();
  relayGet.mockImplementation(async () => structuredClone(server));
  relayPost.mockResolvedValue({ status: "running" });
});
afterEach(() => cleanup());

function mountSweep(accountId: string | null, onSettled?: (s: SweepStatus) => void) {
  return renderHook(
    ({ acct }: { acct: string | null }) =>
      useVaultSweep({ kind: "describe-all", accountId: acct, onSettled }),
    { wrapper, initialProps: { acct: accountId } },
  );
}

describe("a sweep this tab did not start", () => {
  it("shows progress on mount — the reload / second-tab case", async () => {
    server = { running: true, progress: { total: 500, done: 232, capped: false, failed: 7 } };

    const { result } = mountSweep(AID);

    await waitFor(() => expect(result.current.running).toBe(true));
    expect(result.current.busy).toBe(true);
    expect(result.current.progress).toMatchObject({ done: 232, total: 500 });
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("pressing the button again does not start a second sweep, and keeps the label", async () => {
    server = { running: true, progress: { total: 500, done: 232, capped: false } };
    relayPost.mockRejectedValue(new Error("409 describe_already_running"));

    const { result } = mountSweep(AID);
    await waitFor(() => expect(result.current.running).toBe(true));

    await result.current.start({ force: false });

    expect(result.current.busy).toBe(true);
    expect(result.current.progress).toMatchObject({ done: 232 });
    expect(relayPost).toHaveBeenCalledTimes(1);
  });
});

describe("start's answer (the Scripts page's Fill dialog shows the refusal)", () => {
  const KEY = {
    error: "api_key_missing" as const, feature: "describe_media", provider: "typesafe", fix_url: "/settings",
    message: "No vision key is set.", fix: "Paste one in Settings › AI keys.",
  };
  const CAP = "Today's AI budget for this account is spent — $1.00. It resets at 00:00 UTC.";
  it.each<[string, () => Promise<unknown>, string | null]>([
    ["200 running → null", async () => ({ status: "running" }), null],
    ["200 zero-work done → null", async () => ({ status: "done", target: 1000, target_remaining: 0 }), null],
    ["409 already running → null", async () => {
      throw new RelayError(409, { detail: { error: "describe_already_running" } }, "{\"error\":\"describe_already_running\"}");
    }, null],
    ["429 cap → its blocked_reason", async () => {
      throw new RelayError(429, { detail: { error: "daily_cap_reached", capped: true, blocked_reason: CAP } }, "{json}");
    }, CAP],
    ["424 key → message and fix", async () => {
      throw new ApiKeyError(424, { detail: KEY }, KEY);
    }, "No vision key is set. Paste one in Settings › AI keys."],
    ["403 role string → that sentence", async () => {
      throw new RelayError(403, { detail: "Your role does not allow Vault Pro" }, "Your role does not allow Vault Pro");
    }, "Your role does not allow Vault Pro"],
  ])("%s", async (_n, answer, want) => {
    relayPost.mockImplementation(answer);
    const { result } = mountSweep(AID);
    await waitFor(() => expect(relayGet).toHaveBeenCalled());
    expect(await result.current.start({ target: 1000 })).toBe(want);
    expect(relayPost).toHaveBeenCalledWith(
      "/admin/vault-ai/describe-all", { account_id: AID, target: 1000 }, { accountId: AID },
    );
  });
});

describe("the running→idle edge", () => {
  it("fires onSettled exactly once, with the final status", async () => {
    server = { running: true, progress: { total: 500, done: 499, capped: false } };
    const onSettled = vi.fn();

    const { result } = mountSweep(AID, onSettled);
    await waitFor(() => expect(result.current.running).toBe(true));
    expect(onSettled).not.toHaveBeenCalled();

    server = { running: false, progress: { total: 500, done: 500, capped: false, needs_review: 12 } };
    await client.refetchQueries({ queryKey: sweepStatusKey("describe-all", AID) });
    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(1));
    expect(onSettled.mock.calls[0][0].progress).toMatchObject({ needs_review: 12 });

    await client.refetchQueries({ queryKey: sweepStatusKey("describe-all", AID) });
    await client.refetchQueries({ queryKey: sweepStatusKey("describe-all", AID) });
    expect(onSettled).toHaveBeenCalledTimes(1);
  });

  it("does not fire when the account chip changes mid-sweep", async () => {
    server = { running: true, progress: { total: 500, done: 232, capped: false } };
    const onSettled = vi.fn();

    const { result, rerender } = mountSweep(AID, onSettled);
    await waitFor(() => expect(result.current.running).toBe(true));

    server = { running: false, progress: null };
    rerender({ acct: "8000149" });
    await waitFor(() => expect(result.current.running).toBe(false));
    expect(onSettled).not.toHaveBeenCalled();
  });
});

describe("label maths", () => {
  it("prefers the live counter", () => {
    expect(sweepCounts({ total: 500, done: 232 }, { done: 190, total: 463 }))
      .toEqual({ done: 232, total: 500 });
  });

  it("falls back to the durable count when the relay has no counter", () => {
    expect(sweepCounts(null, { done: 190, total: 463 })).toEqual({ done: 190, total: 463 });
  });

  it("shows starting… rather than a 0/0 that reads as breakage", () => {
    expect(sweepCounts(null, { done: 0, total: 0 })).toBeNull();
    expect(describeSweepText(null).label).toBe("starting…");
    expect(harvestSweepLabel(null)).toBe("starting…");
  });

  it("keeps failures off the button but in the tooltip", () => {
    const { label, title } = describeSweepText({
      total: 500, done: 232, capped: false, failed: 7,
      error: "deepinfra HTTP 400: cannot identify image file",
    });
    expect(label).toBe("232/500");
    expect(title).toContain("7 could not be described.");
    expect(title).toContain("cannot identify image file");
  });

  it("names the Jev cap on its own line even when another failure came first (W30 R5)", () => {
    const cap = "Jev daily cap reached earlier in this sweep — Jev skipped";
    const p = { total: 9, done: 9, failed: 5, error: "frame decode failed", notice: cap };
    expect(describeSweepText(p).title).toContain(cap);
    const now = Date.parse("2026-11-14T12:00:00Z");
    const note = sweepAbortedNote({ ...p, finished_at: new Date(now - 60e3).toISOString() }, now);
    expect(note?.detail).toBe(`First error: frame decode failed\n${cap}`);
    expect(sweepAbortedNote({ ...p, error: cap, finished_at: new Date(now - 60e3).toISOString() }, now)?.detail)
      .toBe(`First error: ${cap}`);
  });

  it("keeps a recorded Jev cap line when a later stop or death ends the sweep (W30 C7)", () => {
    const cap = "Jev daily cap reached earlier in this sweep — Jev skipped";
    const stop = { message: "Stopped: Jev (TypeSafe) failed 3 calls in a row.", fix: "Try again later." };
    const p = { total: 9, done: 4, failed: 3, error: "ConnectError: down", notice: cap };
    expect(sweepAbortedNote({ ...p, stop })?.detail).toBe(`Try again later.\n${cap}`);
    expect(sweepAbortedNote({ ...p, aborted: true })?.detail).toBe(`ConnectError: down\n${cap}`);
    expect(sweepAbortedNote({ ...p, stop, notice: undefined })?.detail).toBe("Try again later.");
  });

  it("marks a cap hit on the button, where it changes what you do next", () => {
    expect(describeSweepText({ total: 500, done: 232, capped: true }).label)
      .toBe("232/500 (cap hit)");
  });

  it("says a sweep DIED, because otherwise it looks like one that finished", () => {
    const note = sweepAbortedNote({
      total: 832, done: 214, aborted: true,
      error: "RuntimeError: OF read blew up mid-collect",
    });
    expect(note?.text).toContain("618 left");
    expect(note?.text).toContain("Press again");
    expect(note?.detail).toContain("OF read blew up");
  });

  it("stays quiet about an UNDATED or clean finish (snapshot outlives the run)", () => {
    expect(sweepAbortedNote({ total: 500, done: 500, failed: 7, error: "boom" })).toBeNull();
    expect(sweepAbortedNote({ total: 500, done: 500, finished_at: new Date().toISOString() })).toBeNull();
    expect(sweepAbortedNote(null)).toBeNull();
  });

  it("prints a STOP with the relay's own sentences (11-14: bad key, 5336/5336 failed silently)", () => {
    const note = sweepAbortedNote({
      total: 5336, done: 25, failed: 25,
      stop: { message: "Stopped: 25 items in a row failed.", fix: "First error: 401. Fix it, then press again." },
    });
    expect(note).toEqual({ text: "Stopped: 25 items in a row failed.", detail: "First error: 401. Fix it, then press again.", tone: "warn" });
    const key = sweepAbortedNote({ total: 9, done: 1, key_error: { error: "api_key_invalid", feature: "describe_media", provider: "typesafe", fix_url: "/settings", message: "Key rejected", fix: "Paste a new one" } });
    expect(key?.text).toBe("Key rejected");
  });

  it.each<[string, number, number, number, "warn" | "info" | null]>([
    ["all failed, 1 h ago → warn", 500, 500, 3600e3, "warn"],
    ["some failed → info", 500, 7, 60e3, "info"],
    ["older than 24 h → quiet", 500, 500, 25 * 3600e3, null],
  ])("finished with failures: %s", (_n, done, failed, age, tone) => {
    const now = Date.parse("2026-11-14T12:00:00Z");
    const note = sweepAbortedNote(
      { total: 500, done, failed, error: "TypeSafeAuthenticationError", finished_at: new Date(now - age).toISOString() },
      now,
    );
    expect(note?.tone ?? null).toBe(tone);
    if (tone) {
      expect(note?.text).toContain(`${failed} of 500 failed`);
      expect(note?.detail).toBe("First error: TypeSafeAuthenticationError");
    }
  });

  it.each<[string, Parameters<typeof harvestSweepLabel>[0], string]>([
    ["counts harvest matches", { total: 50, done: 12, matches: 340 }, "12/50 · 340 hits"],
    ["a real zero still shows", { total: 50, done: 50, matches: 0 }, "50/50 · 0 hits"],
    ["folder-limited chatter (matches null): no hit count, not \"0 hits\"", { total: 50, done: 12, matches: null }, "12/50"],
    ["no progress yet", null, "starting…"],
  ])("harvestSweepLabel: %s", (_n, progress, want) => {
    expect(harvestSweepLabel(progress)).toBe(want);
  });
});
